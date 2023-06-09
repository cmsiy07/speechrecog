#-*- coding: utf-8 -*-

import os
import json
import pdb
import argparse
import time
import torch
import torch.nn as nn
import torchaudio
#from torchaudio.models.decoder import ctc_decoder
import soundfile
import numpy as np
import editdistance
import pickle
from tqdm import tqdm
import torch.optim as optim
from math import log




## ===================================================================
## Load labels
## ===================================================================

def load_label_json(labels_path):
    with open(labels_path, encoding="utf-8") as label_file:
        labels = json.load(label_file)
        char2index = dict()
        index2char = dict()

        for index, char in enumerate(labels):
            char2index[char] = index
            index2char[index] = char
            
        return char2index, index2char

## ===================================================================
## Data loader
## ===================================================================

class SpeechDataset(torch.utils.data.Dataset):
    def __init__(self, data_list, data_path, max_length, char2index):
        super(SpeechDataset, self).__init__()

        # load data from JSON
        with open(data_list,'r', encoding="utf-8") as f:
            data = json.load(f)

        # convert seconds to frames
        max_length *= 16000

        # sort data in length order and filter data lessƒ than max_length
        data = sorted(data, key=lambda d: d['len'], reverse=True)
        self.data = [x for x in data if x['len'] <= max_length]

        self.dataset_path   = data_path
        self.char2index     = char2index

    def __getitem__(self, index):

        # read audio using soundfile.read
        # < fill your code here >
        #print("self.dataset_path" + self.dataset_path + self.data[index]['file'])
       # print("self.char2index", self.data['file'])
        #audio = soundfile.read(self.data['file'])
        audio, sample_rate = soundfile.read(os.path.join(self.dataset_path, self.data[index]['file']))

        
        # read transcript and convert to indices
        transcript = self.data[index]['text']
        transcript = self.parse_transcript(transcript)

        return torch.FloatTensor(audio), torch.LongTensor(transcript)

    def parse_transcript(self, transcript):
        transcript = list(filter(None, [self.char2index.get(x) for x in list(transcript)]))
        return transcript

    def __len__(self):
        return len(self.data)


## ===================================================================
## Define collate function
## ===================================================================

def pad_collate(batch):
    (xx, yy) = zip(*batch)

    ## compute lengths of each item in xx and yy
    x_lens = [len(x) for x in xx]
    y_lens = [len(y) for y in yy]

    ## zero-pad to the longest length
    xx_pad = torch.nn.utils.rnn.pad_sequence(xx, batch_first = True, padding_value = 0)
    yy_pad = torch.nn.utils.rnn.pad_sequence(yy, batch_first = True, padding_value = 0)

    return xx_pad, yy_pad, x_lens, y_lens

## ===================================================================
## Define sampler 
## ===================================================================

class BucketingSampler(torch.utils.data.sampler.Sampler):
    def __init__(self, data_source, batch_size=1):
        """
        Samples batches assuming they are in order of size to batch similarly sized samples together.
        """
        super(BucketingSampler, self).__init__(data_source)
        self.data_source = data_source
        ids = list(range(0, len(data_source)))
        self.bins = [ids[i:i + batch_size] for i in range(0, len(ids), batch_size)]

    def __iter__(self):

        # Shuffle bins in random order
        np.random.shuffle(self.bins)

        # For each bin
        for ids in self.bins:
            # Shuffle indices in random order
            np.random.shuffle(ids)
            yield ids

    def __len__(self):
        return len(self.bins)

## ===================================================================
## Baseline speech recognition model
## ===================================================================

class SpeechRecognitionModel(nn.Module):

    def __init__(self, n_classes=11):
        super(SpeechRecognitionModel, self).__init__()
        
        cnns = [nn.Dropout(0.1),  
                nn.Conv1d(40,64,3, stride=1, padding=1),
                nn.BatchNorm1d(64),
                nn.ReLU(),
                nn.Dropout(0.1),  
                nn.Conv1d(64,64,3, stride=1, padding=1),
                nn.BatchNorm1d(64),
                nn.ReLU()] 

        for i in range(2):
          cnns += [nn.Dropout(0.1),  
                   nn.Conv1d(64,64, 3, stride=1, padding=1),
                   nn.BatchNorm1d(64),
                   nn.ReLU()]

        ## define CNN layers
        self.cnns = nn.Sequential(*nn.ModuleList(cnns))

        ## define RNN layers as self.lstm - use a 3-layer bidirectional LSTM with 256 output size and 0.1 dropout
        # < fill your code here >
        self.lstm = nn.LSTM(64,256,3, bidirectional=True, dropout=0.1, batch_first = True)

        ## define the fully connected layer
        self.classifier = nn.Linear(512,n_classes)

        self.preprocess   = torchaudio.transforms.MFCC(sample_rate=8000, n_mfcc=40)
        self.instancenorm = nn.InstanceNorm1d(40)

    def forward(self, x):

        ## compute MFCC and perform mean variance normalisation
        with torch.no_grad():
          x = self.preprocess(x)+1e-6
          x = self.instancenorm(x).detach()

        ## pass the network through the CNN layers
        x = self.cnns(x)

        ## pass the network through the RNN layers - check the input dimensions of nn.LSTM()
        x = self.lstm(x.transpose(1,2))[0]

        ## pass the network through the classifier
        x = self.classifier(x)

        return x

## ===================================================================
## Train an epoch on GPU
## ===================================================================

def process_epoch(model,loader,criterion,optimizer,trainmode=True):

    # Set the model to training or eval mode
    if trainmode:
        model.train()
    else:
        model.eval()

    ep_loss = 0
    ep_cnt  = 0

    with tqdm(loader, unit="batch") as tepoch:

        for data in tepoch:

            ## Load x and y
            x = data[0].cuda()
            y = data[1].cuda()
            y_len = torch.LongTensor(data[3])

            #print(x, y)

            # < fill your code here >

            ## Add some noise to x 
            x = x + torch.normal(mean=0,std=torch.std(x)*1e-3,size=x.shape).cuda()
      
            ## Forward pass
            output = model(x)

            ## Take the log softmax - the output must be in (time, batch, n_class) order
            output = torch.nn.functional.log_softmax(output, dim=2)
            output = output.transpose(0,1)

            ## compute the loss using the CTC objective
            x_len = torch.LongTensor([output.size(0)]).repeat(output.size(1))
            loss = criterion(output, y, x_len, y_len)

            if trainmode:
              # < fill your code here >
              ## Backward pass
                loss.backward()

                ## Optimizer step
                optimizer.step()
                optimizer.zero_grad()

            # keep running average of loss
            ep_loss += loss.item() * len(x)
            ep_cnt  += len(x)

            # print value to TQDM
            tepoch.set_postfix(loss=ep_loss/ep_cnt)

    return ep_loss/ep_cnt


## ===================================================================
## Greedy CTC Decoder
## ===================================================================

class GreedyCTCDecoder(torch.nn.Module):
    def __init__(self, blank=0):
        super().__init__()
        blank = 0
        self.blank = blank

    def forward(self, emission: torch.Tensor):
        """
        Given a sequence emission over labels, get the best path.
        """      
        #print(self.blank)
        indices = torch.argmax(emission, dim = -1)
        #remove the repeats 
        indices = torch.unique_consecutive(indices, dim=-1)
        indices = np.array(indices)
        indices = [i for i in indices if i!=self.blank]
        #print("indices", indices)
        return indices


class beam_search_decoder(torch.nn.Module):
    def __init__(self, blank = 0):
        super().__init__()
        blank = 0 
        self.blank = blank
    # first convert logits to probabilites so that all numbers are +ve
    def forward(self, emission:torch.Tensor):
        k=3
        sequences = [[list(), 0.0]]
        # walk over each step in sequence
        for row in emission:
            all_candidates = list()
            # expand each current candidate
            for i in range(len(sequences)):
                seq, score = sequences[i]
    #             for j in range(len(row)): # instead of exploring all the labels, explore only k best at the current time
                # select k best
                best_k = np.argsort(row)[-k:]
                # explore k best
                for j in best_k:
                    candidate = [seq + [j], score + torch.log(row[j])]
                    all_candidates.append(candidate)
            # order all candidates by score
            ordered = sorted(all_candidates, key=lambda tup:tup[1], reverse=True)
            # select k best
            sequences = ordered[:k]
            
        #remove the repeats
        
        #sequences = torch.Tensor(sequences)
        #indices = torch.tensor(indices[0])
        #torch.unsqueeze(indices[0],0)
        #print(sequences)
        print(len(sequences))
        sequences = torch.stack(sequences[1][0])
        #print(sequences)
        sequences = torch.unique_consecutive(sequences, dim = -1)
        sequences = np.array(sequences)
        sequences = [i for i in sequences if i!=self.blank]

        return sequences
       

        

## ===================================================================
## Evaluation script
## ===================================================================

def process_eval(model,data_path,data_list,index2char,save_path=None):

    # set model to evaluation mode
    model.eval()
    #model.to(torch.double)


    # initialise the greedy decoder
    #current_decoder
    #c_decoder = GreedyCTCDecoder(blank=len(index2char))
    c_decoder = beam_search_decoder()

    # load data from JSON
    with open(data_list,'r', encoding="utf-8") as f:
        data = json.load(f)

    results = []

    for file in tqdm(data):

        # read the wav file and convert to PyTorch format
        audio, sample_rate = soundfile.read(os.path.join(data_path, file['file']))
        # < fill your code here >
        x = torch.FloatTensor(audio).unsqueeze(0).cuda()

        #add some noise 
        x = x + torch.normal(mean=0, std=torch.std(x)*1e-3, size =x.shape).cuda()
        #x.double()
   
        # forward pass through the model
        # < fill your code here >
        with torch.no_grad():
            output = model(x)
            output = torch.nn.functional.log_softmax(output, dim=2)
            output =output.transpose(0,1)

        # decode using the greedy decoder
        # < fill your code here >
        #print("output:", output)
        #returns a list of predicted indices 
        #compute all indices then compute minimum CER 
        pred = c_decoder(output.cpu().detach().squeeze())
        print(pred)

        # convert to text
        out_text = ''.join([index2char[x] for x in pred])

        # keep log of the results
        file['pred'] = out_text
        if 'text' in file:
            file['edit_dist']   = editdistance.eval(out_text.replace(' ',''),file['text'].replace(' ',''))
            file['gt_len']     = len(file['text'].replace(' ',''))
        results.append(file)
    
    # save results to json file
    with open(os.path.join(save_path,'results.json'), 'w', encoding='utf-8') as outfile:
        json.dump(results, outfile, ensure_ascii=False, indent=2)

    # print CER if there is ground truth
    if 'text' in file:
        cer = sum([x['edit_dist'] for x in results]) / sum([x['gt_len'] for x in results])
        print('Character Error Rate is {:.2f}%'.format(cer*100))


## ===================================================================
## Main execution script
## ===================================================================

def main():

    parser = argparse.ArgumentParser(description='EE738 Exercise')

    print(torch.__version__)
    print(torchaudio.__version__)
    
    #..\SpeechRecog\ee738filelist
    #/home/EE728
    ## related to data loading
    parser.add_argument('--max_length', type=int, default=10,   help='maximum length of audio file in seconds')
    parser.add_argument('--train_list', type=str, default='../../SpeechRecog/ee738_2023_filelist/ks_train.json')
    parser.add_argument('--val_list',   type=str, default='../../SpeechRecog/ee738_2023_filelist/ks_val.json')
    parser.add_argument('--labels_path',type=str, default='../../SpeechRecog/ee738_2023_filelist/label.json')
    parser.add_argument('--train_path', type=str, default='../../SpeechRecog/kspon_train')
    parser.add_argument('--val_path',   type=str, default='../../SpeechRecog/kspon_eval')


    ## related to training
    parser.add_argument('--max_epoch',  type=int, default=10,       help='number of epochs during training')
    parser.add_argument('--batch_size', type=int, default=50,      help='batch size')
    parser.add_argument('--lr',         type=int, default=1e-4,     help='learning rate')
    parser.add_argument('--seed',       type=int, default=2222,     help='random seed initialisation')
    
    ## relating to loading and saving
    parser.add_argument('--initial_model',  type=str, default='',   help='load initial model, e.g. for finetuning')
    parser.add_argument('--save_path',      type=str, default='',   help='location to save checkpoints')

    ## related to inference
    parser.add_argument('--eval',   dest='eval',    action='store_true', help='Evaluation mode')

    args = parser.parse_args()

    # load labels
    char2index, index2char = load_label_json(args.labels_path)

    ## make an instance of the model on GPU
    model = SpeechRecognitionModel(n_classes=len(char2index)+1).cuda()
    print('Model loaded. Number of parameters:',sum(p.numel() for p in model.parameters()))

    ## load from initial model
    if args.initial_model != '':
        model.load_state_dict(torch.load(args.initial_model))

    # make directory for saving models and output
    assert args.save_path != ''
    os.makedirs(args.save_path,exist_ok=True)

    ## code for inference - this uses val_path and val_list
    if args.eval:
        process_eval(model, args.val_path, args.val_list, index2char, save_path=args.save_path)
        quit();

    # initialise seeds
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    np.random.seed(args.seed)

    print(args.train_list)
    print(args.train_path)

    # define datasets
    trainset  = SpeechDataset(args.train_list, args.train_path, args.max_length, char2index)
    valset    = SpeechDataset(args.val_list,   args.val_path,   args.max_length, char2index)

    # initiate loader for each dataset with 'collate_fn' argument
    # do not use more than 6 workers
    trainloader = torch.utils.data.DataLoader(trainset, 
        batch_sampler=BucketingSampler(trainset, args.batch_size), 
        num_workers=4, 
        collate_fn=pad_collate,
        prefetch_factor=4)
    valloader   = torch.utils.data.DataLoader(valset,   
        batch_sampler=BucketingSampler(valset, args.batch_size), 
        num_workers=4, 
        collate_fn=pad_collate,
        prefetch_factor=4)

    ## define the optimizer with args.lr learning rate and appropriate weight decay
    # < fill your code here >
    optimizer = optim.Adam(model.parameters(), lr=(args.lr), weight_decay=1e-5)


    ## set loss function with blank index
    ctcloss = nn.CTCLoss(blank=0).cuda()

    ## initialise training log file
    f_log = open(os.path.join(args.save_path,'train.log'),'a+')
    f_log.write('{}\n'.format(args))
    f_log.flush()

    ## Train for args.max_epoch epochs
    for epoch in range(0, args.max_epoch):

        # < fill your code here >
        print('Training epoch', epoch)
        tloss = process_epoch(model,trainloader,ctcloss,optimizer,trainmode=True)

        print('Validating epoch', epoch)
        vloss = process_epoch(model,valloader,ctcloss,optimizer,trainmode=False)

        # save checkpoint to file
        save_file = '{}/model{:05d}.pt'.format(args.save_path,epoch)
        print('Saving model {}'.format(save_file))
        torch.save(model.state_dict(), save_file)

        # write training progress to log
        f_log.write('Epoch {:03d}, train loss {:.3f}, val loss {:.3f}\n'.format(epoch, tloss, vloss))
        f_log.flush()

    f_log.close()


if __name__ == "__main__":
    

    main()
