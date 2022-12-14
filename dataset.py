import torch
from torch.utils.data import Dataset, DataLoader

import numpy as np
import math
import os

import hparams
import audio as Audio
from utils import pad_1D, pad_2D, process_meta, standard_norm
from text import text_to_sequence, sequence_to_text
import time
import json

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


class Dataset(Dataset):
    def __init__(self, filename="train.txt", sort=True):
        self.basename, self.speaker, self.text = process_meta(os.path.join(hparams.preprocessed_path, filename))
        
        self.mean_mel, self.std_mel = np.load(os.path.join(hparams.preprocessed_path, "mel_stat.npy"))
        self.mean_f0, self.std_f0 = np.load(os.path.join(hparams.preprocessed_path, "f0_stat.npy"))
        self.mean_energy, self.std_energy = np.load(os.path.join(hparams.preprocessed_path, "energy_stat.npy"))

        with open(os.path.join(hparams.preprocessed_path, "speakers.json"), "r",) as f:
            self.speaker_map = json.load(f)
        
        self.sort = sort

    def __len__(self):
        return len(self.text)

    def __getitem__(self, idx):
        t=self.text[idx]
        basename=self.basename[idx]
        speaker = self.speaker[idx]
        speaker_id = self.speaker_map[speaker]
        phone = np.array(text_to_sequence(t, []))
        
        mel_path = os.path.join(
            hparams.preprocessed_path, "mel", "{}-mel-{}.npy".format(hparams.dataset, basename))
        mel_target = np.load(mel_path)
        D_path = os.path.join(
            hparams.preprocessed_path, "alignment", "{}-ali-{}.npy".format(hparams.dataset, basename))
        D = np.load(D_path)
        f0_path = os.path.join(
            hparams.preprocessed_path, "f0", "{}-f0-{}.npy".format(hparams.dataset, basename))
        f0 = np.load(f0_path)
        energy_path = os.path.join(
            hparams.preprocessed_path, "energy", "{}-energy-{}.npy".format(hparams.dataset, basename))
        energy = np.load(energy_path)
        
        sample = {"id": basename,
                  "speaker": speaker_id,
                  "text": phone,
                  "mel_target": mel_target,
                  "D": D,
                  "f0": f0,
                  "energy": energy}
        return sample


    def reprocess(self, batch, cut_list):
        ids = [batch[ind]["id"] for ind in cut_list]
        speakers = [batch[ind]["speaker"] for ind in cut_list]
        texts = [batch[ind]["text"] for ind in cut_list]
        mel_targets = [standard_norm(batch[ind]["mel_target"], self.mean_mel, self.std_mel, is_mel=True) for ind in cut_list]
        Ds = [batch[ind]["D"] for ind in cut_list]
        f0s = [standard_norm(batch[ind]["f0"], self.mean_f0, self.std_f0) for ind in cut_list]
        energies = [standard_norm(batch[ind]["energy"], self.mean_energy, self.std_energy) for ind in cut_list]

        for text, D, id_ in zip(texts, Ds, ids):
            if len(text) != len(D):
                print('the dimension of text and duration should be the same')
                print('text: ',sequence_to_text(text))
                print(text, text.shape, D, D.shape, id_)
        length_text = np.array(list())
        for text in texts:
            length_text = np.append(length_text, text.shape[0])

        length_mel = np.array(list())
        for mel in mel_targets:
            length_mel = np.append(length_mel, mel.shape[0])

        speakers = np.array(speakers) 
        texts = pad_1D(texts)
        Ds = pad_1D(Ds)
        mel_targets = pad_2D(mel_targets)
        f0s = pad_1D(f0s)
        energies = pad_1D(energies)
        log_Ds = np.log(Ds + hparams.log_offset)

        out = {"id": ids,
               "speaker": speakers,
               "text": texts,
               "mel_target": mel_targets,
               "D": Ds,
               "log_D": log_Ds,
               "f0": f0s,
               "energy": energies,
               "src_len": length_text,
               "mel_len": length_mel}
        
        return out

    def collate_fn(self, batch):
        len_arr = np.array([d["text"].shape[0] for d in batch])
        index_arr = np.argsort(-len_arr)
        batchsize = len(batch)
        real_batchsize = int(math.sqrt(batchsize))

        cut_list = list()
        for i in range(real_batchsize):
            if self.sort:
                cut_list.append(index_arr[i*real_batchsize:(i+1)*real_batchsize])
            else:
                cut_list.append(np.arange(i*real_batchsize, (i+1)*real_batchsize))
        
        output = list()
        for i in range(real_batchsize):
            output.append(self.reprocess(batch, cut_list[i]))

        return output

if __name__ == "__main__":
    # Test
    dataset = Dataset('val.txt')
    training_loader = DataLoader(dataset, batch_size=1, shuffle=False, collate_fn=dataset.collate_fn,
        drop_last=True, num_workers=0)
    total_step = hparams.epochs * len(training_loader) * hparams.batch_size

    cnt = 0
    for i, batchs in enumerate(training_loader):
        for j, data_of_batch in enumerate(batchs):
            mel_target = torch.from_numpy(
                data_of_batch["mel_target"]).float().to(device)
            D = torch.from_numpy(data_of_batch["D"]).int().to(device)
            if mel_target.shape[1] == D.sum().item():
                cnt += 1

