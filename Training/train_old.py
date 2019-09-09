# TODO

import os,sys,inspect
currentdir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
parentdir = os.path.dirname(currentdir)
sys.path.insert(0,parentdir)

ncpu="10"
import os
os.environ["OMP_NUM_THREADS"] = ncpu # export OMP_NUM_THREADS=4
os.environ["OPENBLAS_NUM_THREADS"] = ncpu # export OPENBLAS_NUM_THREADS=4
os.environ["MKL_NUM_THREADS"] = ncpu # export MKL_NUM_THREADS=4
os.environ["VECLIB_MAXIMUM_THREADS"] = ncpu # export VECLIB_MAXIMUM_THREADS=4
os.environ["NUMEXPR_NUM_THREADS"] = ncpu # export NUMEXPR_NUM_THREADS=4
import numpy as np

import gc
import psutil
from Training.class_network import my_bilstm
from Training.modele import my_ac2art_modele
import sys
import torch
import os
import csv
import sys
from sklearn.model_selection import train_test_split
from Training.utils import load_filenames, load_data, load_filenames_deter
from Training.pytorchtools import EarlyStopping
import time
import random
from os.path import dirname
from scipy import signal
import matplotlib.pyplot as plt
from Traitement.fonctions_utiles import get_speakers_per_corpus
import scipy
from os import listdir
from logger import Logger
import json


root_folder = os.path.dirname(os.getcwd())
fileset_path = os.path.join(root_folder, "Donnees_pretraitees", "fileset")

print(sys.argv)


def memReport(all = False):
    # TODO: tu l'uilises ça ?
    nb_object = 0
    for obj in gc.get_objects():
        if torch.is_tensor(obj):
            if all:
                print(type(obj), obj.size())
            nb_object += 1
    print('nb objects tensor', nb_object)


def cpuStats():
    # TODO : tu l'utilises ça ?
    print(sys.version)
    print(psutil.cpu_percent())
    print(psutil.virtual_memory())  # physical memory usage
    pid = os.getpid()
    py = psutil.Process(pid)
    memoryUse = py.memory_info()[0] / 2. ** 30  # memory use in GB...I think
    print('memory GB:', memoryUse)



def train_model(test_on ,n_epochs ,loss_train,patience ,select_arti,corpus_to_train_on,batch_norma,filter_type,
                train_a_bit_on_test ):
    # TODO: elle est un peu longue cette foncton, il y a aucun moyen pour que tu la découpes en sous fonctions ?
    name_corpus_concat = ""
    train_on = []
    delta_test=  1
    lr = 0.001
    to_plot = False
    corpus_to_train_on = corpus_to_train_on[1:-1].split(",")
    for corpus in corpus_to_train_on :
        sp = get_speakers_per_corpus(corpus)
        train_on = train_on + sp
        name_corpus_concat = name_corpus_concat+corpus+"_"


       # elif "usc" in corpus_to_train_on:
        #    train_on = ["M3","MNGU0"]
       # elif "Haskins" in corpus_to_train_on:
        #    train_on = ["F02"]

    if test_on in train_on :
        train_on.remove(test_on)
    print("train on :",train_on," test on ",test_on)
    #train_on = ["msak0"]
    cuda_avail = torch.cuda.is_available()
    print(" cuda ?", cuda_avail)
    if cuda_avail :
        device = torch.device("cuda")
    else :
        device = torch.device("cpu")

    suff = ""
    if train_a_bit_on_test :
        suff = "and_"+test_on+"_"
    name_file = "train_on_"+name_corpus_concat+suff+"test_on_"+test_on+"_idx_"+str(select_arti)\
                +"_loss_"+str(loss_train)+"_typefilter_"+str(filter_type)+"_bn_"+str(batch_norma)


    previous_models = os.listdir("saved_models")
    previous_models_2 = [x[:len(name_file)] for x in previous_models if x.endswith(".txt")]
    n_previous_same = previous_models_2.count(name_file)
    if n_previous_same > 0:
        print("this models has alread be trained {} times".format(n_previous_same))
    else :
        print("first time for this model")
    name_file = name_file + "_" + str(n_previous_same)
    print("name file",name_file)
    logger = Logger('./logs')

    hidden_dim = 300
    input_dim = 429
    batch_size = 10
    output_dim = 18


    early_stopping = EarlyStopping(name_file,patience=patience, verbose=True)

    model = my_ac2art_modele(hidden_dim=hidden_dim, input_dim=input_dim, name_file=name_file, output_dim=output_dim,
                      batch_size=batch_size, cuda_avail=cuda_avail,
                      modele_filtered=filter_type,batch_norma=batch_norma)
    model = model.double()
   # file_weights = os.path.join("saved_models", name_file +".txt")
    file_weights = os.path.join("saved_models", name_file +".pt")

    if cuda_avail:
        model = model.to(device = device)
       # cuda = torch.device('cuda')

    load_old_model = True
    if load_old_model:
     if os.path.exists(file_weights):
        print("modèle précédent pas fini")
        loaded_state = torch.load(file_weights,map_location = device)
        model.load_state_dict(loaded_state)

        model_dict = model.state_dict()
        loaded_state = {k: v for k, v in loaded_state.items() if
                        k in model_dict}  # only layers param that are in our current model
        loaded_state = {k: v for k, v in loaded_state.items() if
                        loaded_state[k].shape == model_dict[k].shape}  # only if layers have correct shapes
        model_dict.update(loaded_state)
        model.load_state_dict(model_dict)


    def criterion_pearson(my_y,my_y_pred): # (L,K,13)
        # TODO
        y_1 = my_y - torch.mean(my_y,dim=1,keepdim=True)
        y_pred_1 = my_y_pred - torch.mean(my_y_pred,dim=1,keepdim=True)
        nume=  torch.sum(y_1* y_pred_1,dim=1,keepdim=True) # y*y_pred multi terme à terme puis on somme pour avoir (L,1,13)
      #pour chaque trajectoire on somme le produit de la vriae et de la predite
        deno =  torch.sqrt(torch.sum(y_1 ** 2,dim=1,keepdim=True)) * torch.sqrt(torch.sum(y_pred_1 ** 2,dim=1,keepdim=True))# use Pearson correlation
        # deno zero veut dire ema constant à 0 on remplace par des 1
        minim = torch.tensor(0.01,dtype=torch.float64)
        if cuda_avail:
            minim = minim.to(device=device)
            deno = deno.to(device=device)
            nume = nume.to(device=device)
        deno = torch.max(deno,minim)
        my_loss = torch.div(nume,deno)
        my_loss = torch.sum(my_loss) #pearson doit etre le plus grand possible
        return -my_loss

    criterion_rmse = torch.nn.MSELoss(reduction='sum')

    def criterion_both(L):
        # TODO
        L = L/100 #% de pearson dans la loss
        def criterion_both_lbd(my_y,my_ypred):
            # TODO: evite les fonctions imbriquées
            a = L * criterion_pearson(my_y, my_ypred)
            b = (1 - L) * criterion_rmse(my_y, my_ypred) / 1000
            new_loss = a + b
          #  print(a,b,new_loss)
           # return new_loss
            return new_loss
        return criterion_both_lbd

    if loss_train == "rmse":
        criterion = criterion_rmse
    elif loss_train == "pearson" :
        print("pearson")
        criterion = criterion_pearson
    elif loss_train[:4] == "both":
        lbd = int(loss_train[5:])
        criterion = criterion_both(lbd)

    with open('categ_of_speakers.json', 'r') as fp:
        categ_of_speakers = json.load(fp) #dictionnaire en clé la categorie en valeur un dictionnaire
                                            # #avec les speakers dans la catégorie et les arti concernées par cette categorie
    optimizer = torch.optim.Adam(model.parameters(), lr=lr ) #, betas = beta_param)


    path_files = os.path.join(os.path.dirname(os.getcwd()),"Donnees_pretraitees","fileset")
    files_for_train = load_filenames_deter(train_on, part=["train", "test"])

    files_for_valid = load_filenames_deter(train_on, part=["valid"])
    files_for_test = load_filenames_deter([test_on], part=["train", "valid", "test"])

    if train_a_bit_on_test :
        files_for_train_this_sp = load_filenames_deter([test_on], part=["train"])
        files_for_train = files_for_train + files_for_train_this_sp
        files_for_valid_this_sp = load_filenames_deter([test_on], part=["valid"])
        print("some testspeaker files in train : ",len(files_for_train_this_sp))
        files_for_valid = files_for_valid + files_for_valid_this_sp

    files_per_categ = dict()
    for categ in categ_of_speakers.keys():
        sp_in_categ = categ_of_speakers[categ]["sp"]
        sp_in_categ = [sp for sp in sp_in_categ if sp in train_on]
        # fichiers qui appartiennent à la categorie car le nom du speaker apparait touojurs dans le nom du fichier
        files_train_this_categ = [[f for f in files_for_train if sp.lower() in f.lower() ]for sp in sp_in_categ]

        files_train_this_categ = [item for sublist in files_train_this_categ for item in sublist] # flatten la liste de liste
        files_valid_this_categ = [[f for f in files_for_valid if sp.lower() in f.lower()] for sp in sp_in_categ]
        files_valid_this_categ = [item for sublist in files_valid_this_categ for item in sublist]  # flatten la liste de liste

        if len(files_train_this_categ) > 0 : #meaning we have at least one file in this categ
            files_per_categ[categ] = dict()
            N_iter_categ = int(len(files_train_this_categ)/batch_size)+1         # on veut qu'il y a en ait un multiple du batch size , on en double certains
            n_a_ajouter = batch_size*N_iter_categ - len(files_train_this_categ) #si 14 element N_iter_categ vaut 2 et n_a_ajouter vaut 6
            files_train_this_categ = files_train_this_categ + files_train_this_categ[:n_a_ajouter] #nbr de fichier par categorie multiple du batch size
            random.shuffle(files_train_this_categ)
            files_per_categ[categ]["train"] = files_train_this_categ
            N_iter_categ = int(len(  files_valid_this_categ) / batch_size) + 1  # on veut qu'il y a en ait un multiple du batch size , on en double certains
            n_a_ajouter = batch_size * N_iter_categ - len(files_valid_this_categ)  # si 14 element N_iter_categ vaut 2 et n_a_ajouter vaut 6
            files_valid_this_categ = files_valid_this_categ + files_valid_this_categ[:n_a_ajouter] # nbr de fichier par categorie multiple du batch size
            random.shuffle(files_valid_this_categ)
            files_per_categ[categ]["valid"] = files_valid_this_categ


    categs_to_consider = files_per_categ.keys()

    plot_filtre_chaque_epochs = False

    for epoch in range(n_epochs):

        weight_apres = model.lowpass.weight.data[0, 0, :]
        #print("GAIN 0",sum(weight_apres.cpu()))
     #   memReport()
        if plot_filtre_chaque_epochs :

            freqs, h = signal.freqz(weight_apres.cpu())
            freqs = freqs * 100 / (2 * np.pi)  # freq in hz
            plt.plot(freqs, 20 * np.log10(abs(h)), 'r')
            plt.title("EPOCH {}".format(epoch))
            plt.ylabel('Amplitude [dB]')
            plt.xlabel("real frequency")
            plt.show()

        n_this_epoch = 0
        random.shuffle(list(categs_to_consider))
        loss_train_this_epoch = 0

        for categ in categs_to_consider:  # de A à F pour le momen
            files_this_categ_courant = files_per_categ[categ]["train"] #on na pas encore apprit dessus au cours de cette epoch
            random.shuffle(files_this_categ_courant)

            while len(files_this_categ_courant) > 0:
                n_this_epoch+=1
                x, y = load_data(files_this_categ_courant[:batch_size])

                files_this_categ_courant = files_this_categ_courant[batch_size:] #we a re going to train on this 10 files
                x, y = model.prepare_batch(x, y)
                #cpuStats()
                #if cuda_avail:
                   # print("x shape", x.shape)
                    #cpuStats()

                y_pred = model(x).double()
                if cuda_avail:
                    y_pred = y_pred.to(device=device)
                y = y.double()
                optimizer.zero_grad()
                if select_arti:
                    arti_to_consider = categ_of_speakers[categ]["arti"]  # liste de 18 0/1 qui indique les arti à considérer
                    idx_to_ignore = [i for i, n in enumerate(arti_to_consider) if n == "0"]
                    y_pred[:, :, idx_to_ignore] = 0
                   # y_pred[:,:,idx_to_ignore].detach()
                    #y[:,:,idx_to_ignore].requires_grad = False

                loss = criterion(y, y_pred)
                loss.backward()
                #a partir de là y_pred.grad a des elements
         #       print("ypred grad shape", y_pred.grad.shape)
                optimizer.step()
                torch.cuda.empty_cache()
                loss_train_this_epoch += loss.item()
                weight_apres = model.lowpass.weight.data[0, 0, :]
             #    print("GAIN 1", sum(weight_apres.cpu()))
        torch.cuda.empty_cache()

        loss_train_this_epoch = loss_train_this_epoch/n_this_epoch

        if epoch%delta_test ==0:  #toutes les delta_test epochs on évalue le modèle sur validation et on sauvegarde le modele si le score est meilleur
         #   x, y = load_data(files_for_test)
          #  print("evaluation on speaker {}".format(test_on))
           # model.evaluate_on_test(x, y, verbose=True, to_plot=to_plot)

          #  print("evaluation validation")
            loss_vali = 0
            n_valid = 0
            for categ in categs_to_consider:  # de A à F pour le moment
                files_this_categ_courant = files_per_categ[categ]["valid"]  # on na pas encore apprit dessus au cours de cette epoch
                while len(files_this_categ_courant) >0 :
                    n_valid +=1
                    x, y = load_data(files_this_categ_courant[:batch_size])
                    files_this_categ_courant = files_this_categ_courant[batch_size:]  # on a appris sur ces 10 phrases
                    x, y = model.prepare_batch(x, y)
                    y_pred = model(x).double()
                    torch.cuda.empty_cache()
                    if cuda_avail:
                        y_pred = y_pred.to(device=device)
                    y = y.double()  # (Batchsize, maxL, 18)

                    if select_arti:
                        arti_to_consider = categ_of_speakers[categ]["arti"]  # liste de 18 0/1 qui indique les arti à considérer
                        idx_to_ignore = [i for i, n in enumerate(arti_to_consider) if n == "0"]
                        y_pred[:, :, idx_to_ignore] = 0
                    #    y_pred[:, :, idx_to_ignore].detach()
                   #     y[:, :, idx_to_ignore].requires_grad = False

                    loss_courant = criterion(y, y_pred)
                    loss_vali += loss_courant.item()
            loss_vali  = loss_vali/n_valid


        model.all_validation_loss.append(loss_vali)
        model.all_training_loss.append(loss_train_this_epoch)
      #  print("all training loss",model.all_training_loss)
        early_stopping(loss_vali, model)

        # ================================================================== #
        #                        Tensorboard Logging                         #
        # ================================================================== #
        # TODO: enlève tous els trucs inutiles

        # 1. Log scalar values (scalar summary)
        info = {'loss': loss_train_this_epoch}

        for tag, value in info.items():
           # print("tag valu",tag,value)
            logger.scalar_summary(tag, value, epoch + 1)

        # 2. Log values and gradients of the parameters (histogram summary)
    #    for tag, value in model.named_parameters():
     #       tag = tag.replace('.', '/')
      #      logger.histo_summary(tag, value.data.cpu().numpy(), epoch + 1)
       #     logger.histo_summary(tag + '/grad', value.grad.data.cpu().numpy(), epoch + 1)

        # 3. Log training images (image summary)
       # info = {'images': images.view(-1, 28, 28)[:10].cpu().numpy()}

        #for tag, images in info.items():
         #   logger.image_summary(tag, images, epoch + 1)
#
        if epoch>0:
            if loss_vali > model.all_validation_loss[-1]:
                for param_group in optimizer.param_groups:
                    param_group['lr'] = param_group['lr'] / 2
                    (param_group["lr"])
                    patience_temp=0

            #model.all_test_loss += [model.all_test_loss[-1]] * (epoch+previous_epoch - len(model.all_test_loss))
           # print("\n ---------- epoch" + str(epoch) + " ---------")
            #early_stopping.epoch = previous_epoch+epoch

          #  print("train loss ", loss.item())
          #  print("valid loss ", loss_vali)

         #   logger.scalar_summary('loss_valid', loss_vali,
          #                        model.epoch_ref)
           # logger.scalar_summary('loss_train', loss.item(), model.epoch_ref)

            torch.cuda.empty_cache()

        if early_stopping.early_stop:
            print("Early stopping, n epochs : ",model.epoch_ref+epoch)
            break
    total_epoch = 0



    if n_epochs>0:
        model.epoch_ref = model.epoch_ref + epoch
        total_epoch =model.epoch_ref
        model.load_state_dict(torch.load(os.path.join("saved_models",name_file+'.pt')))
        torch.save(model.state_dict(), os.path.join( "saved_models",name_file+".txt"))


    random.shuffle(files_for_test)
    x, y = load_data(files_for_test)
    print("evaluation on speaker {}".format(test_on))
    #print("DATA AND MODELE FILTERED")
    std_speaker = np.load(os.path.join(root_folder,"Traitement","norm_values","std_ema_"+test_on+".npy"))
    arti_per_speaker = os.path.join(root_folder, "Traitement", "articulators_per_speaker.csv")
    csv.register_dialect('myDialect', delimiter=';')
    weight_apres = model.lowpass.weight.data[0, 0, :]
  #  print("GAINAAA",sum(weight_apres.cpu()))
    with open(arti_per_speaker, 'r') as csvFile:
        reader = csv.reader(csvFile, dialect="myDialect")
        next(reader)
        for row in reader:
            if row[0] == test_on:
                arti_to_consider = row[1:19]
                arti_to_consider = [int(x) for x in arti_to_consider]
  #  print("arti to cons",arti_to_consider)
    rmse_per_arti_mean, pearson_per_arti_mean = model.evaluate_on_test(x,y, std_speaker = std_speaker, to_plot=to_plot
                                                                       ,to_consider = arti_to_consider) #,filtered=True)
    print("name file : ",name_file)

    with open('resultats_modeles.csv', 'a') as f:
        writer = csv.writer(f)
        row_rmse = [name_file]+rmse_per_arti_mean.tolist()+[model.epoch_ref]
        row_pearson  =[name_file]+pearson_per_arti_mean.tolist() + [model.epoch_ref]
        writer.writerow(row_rmse)
        writer.writerow(row_pearson)
    plot_filtre_chaque_epochs = False

    if plot_filtre_chaque_epochs:
        weight_apres = model.lowpass.weight.data[0, 0, :]
        print("GAIN",sum(weight_apres.cpu()))

        freqs, h = signal.freqz(weight_apres.cpu())
        freqs = freqs * 100 / (2 * np.pi)  # freq in hz
        plt.plot(freqs, 20 * np.log10(abs(h)), 'r')
        plt.title("Allure filtre passe bas à la fin de l'Training pour filtre en dur")
        plt.ylabel('Amplitude [dB]')
        plt.xlabel("real frequency")
        plt.show()

    #x, y = load_data(files_for_test,filtered=False)
   # print("DATA AND MODELE NOT FILTERED")
    #model.evaluate_on_test(x,y, to_plot=to_plot,filtered=False)

if __name__=='__main__':
    # TODO: tous les comments dans le argparse doivent être en anglais
    import argparse
    parser = argparse.ArgumentParser(description='Train and save a model.')
    parser.add_argument('test_on', type=str,
                        help='the speaker we want to test on')

    parser.add_argument('n_epochs', type=int,
                        help='max number of epochs to train the model')
   # parser.add_argument('delta_test', type=int,
    #                    help='interval between two validation evaluation')

    parser.add_argument('loss_train', type=str,
                        help="rmse or pearson or both")
    parser.add_argument('patience', type=int,
                        help='number of iterations in a row with decreasing validation score before stopping the train ')

    # parser.add_argument('lr',    help='learning rate of Adam optimizer ')
#    parser.add_argument('to_plot', type=bool,
 #                       help='si true plot les resultats sur le test')

    parser.add_argument('select_arti', type=bool,
                        help='ssi dans la retropro on ne considere que les arti bons')

    parser.add_argument('corpus_to_train_on',  type=str,
                        help='ssi dans la retropro on ne considere que les arti bons')
   # parser.add_argument('only_one_sp', type=bool,
   #                     help='ssi dans la retropro on ne considere que les arti bons')
    parser.add_argument('batchnorma', type=bool,
                         help='do batch norma')

    parser.add_argument('filter_type', type=int,
                        help='0 pas de lissage, 1 lissage en dur, 2 lissage variable crée avec pytorch, 3 lissage variable cree avec en dur')

    parser.add_argument('train a bit on speaker test', type=bool,
                        help='do you want to add a part of the speaker test in the training set')

    args = parser.parse_args()
    # TODO: pq tu as à la fois des sys.argv et des args?
    test_on =  sys.argv[1]
    n_epochs = int(sys.argv[2])
    loss_train = sys.argv[3]
  #  delta_test = int(sys.argv[3])
    patience = int(sys.argv[4])
 #   lr = float(sys.argv[5])
 #   to_plot = sys.argv[6].lower()=="true"
    select_arti = sys.argv[5].lower()=="true"
    corpus_to_train_on = str(sys.argv[6])
   # only_one_sp = sys.argv[7].lower()=="true"

    batch_norma = sys.argv[7].lower()=="true"

    filter_type = int(sys.argv[8]) # 0 pas de lissage, 1 lissage en dur, 2 lissage variable crée avec pytorch, 3 lissage variable cree avec en dur
    train_a_bit_on_test = sys.argv[9].lower()=="true"
    train_model(test_on = test_on,n_epochs=n_epochs,loss_train = loss_train,patience=patience,
               select_arti=select_arti,corpus_to_train_on = corpus_to_train_on,batch_norma = batch_norma
             ,filter_type=  filter_type, train_a_bit_on_test=train_a_bit_on_test)