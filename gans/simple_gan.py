"""
Import necessary libraries to create a generative adversarial network
The code is developed using the PyTorch library
"""
import os
import pickle
import time
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import MinMaxScaler
import joblib
import matplotlib.pyplot as plt
from sdv.evaluation import evaluate
from sdv.metrics.tabular import KSTest
from statistics import mean
from sklearn.model_selection import train_test_split
from sdv.metrics.tabular import BNLikelihood, BNLogLikelihood, GMLogLikelihood
from sdv.metrics.tabular import LogisticDetection, SVCDetection
import helper_scripts.transform_booleans as transform_bool
import warnings
import seaborn as sns

warnings.filterwarnings('ignore')

"""
Network Architectures
The following are the discriminator and generator architectures
"""


class Discriminator(nn.Module):
    def __init__(self):
        super(Discriminator, self).__init__()
        self.fc1 = nn.Linear(310, 400)
        self.fc2 = nn.Linear(400, 1)
        self.activation = nn.LeakyReLU(0.1)

    def forward(self, x):
        x = x.view(-1, 310)
        x = self.activation(self.fc1(x))
        x = self.fc2(x)
        return nn.Sigmoid()(x)


class Generator(nn.Module):
    def __init__(self):
        super(Generator, self).__init__()
        self.fc1 = nn.Linear(128, 500)
        self.fc2 = nn.Linear(500, 1000)
        self.fc3 = nn.Linear(1000, 310)
        self.activation = nn.ReLU()

    def forward(self, x):
        x = self.activation(self.fc1(x))
        x = self.activation(self.fc2(x))
        x = self.fc3(x)
        x = x.view(-1, 1, 1, 310)
        return nn.Sigmoid()(x)


def prepare_data(data=pickle.load(open('final_data_no_rts_v2', 'rb')), batch_size=64, bots=True):
    df = pd.DataFrame(data)
    # Convert labels from string to 0 and 1
    df['label'] = df['label'].map({'human': 0, 'bot': 1, 'cyborg': 1})
    # df = df.sample(n=100)

    # Keep 20% of the data for later testing
    train_set, test_set = train_test_split(df, test_size=0.2, random_state=42)

    pickle.dump(test_set, open('simple_gan/test_data', 'wb'))

    # Convert features that are boolean to integers
    df = train_set.applymap(lambda x: int(x) if isinstance(x, bool) else x)

    if bots:
        # keep only bot accounts to train our GAN
        df = df[df['label'] == 1]
    else:
        # keep only human accounts to train our GAN
        df = df[df['label'] == 0]

    y = df['label']

    # Drop unwanted columns
    df = df.drop(['user_name', 'user_screen_name', 'user_id', 'label'], axis=1)
    if 'max_appearance_of_punc_mark' in df.columns:
        df = df.drop(['max_appearance_of_punc_mark'], axis=1)

    # Scale our data in the range of (0, 1)
    scaler = MinMaxScaler()
    df_scaled = scaler.fit_transform(X=df)

    # Store scaler for later use
    scaler_filename = "simple_gan/scaler.save"
    joblib.dump(scaler, scaler_filename)

    # Transform dataframe into pytorch Tensor
    train = TensorDataset(torch.Tensor(df_scaled), torch.Tensor(np.array(y)))
    train_loader = DataLoader(dataset=train, batch_size=batch_size, shuffle=True)
    return train_loader, df, pd.DataFrame(df_scaled)


def train_gan(epochs=100, bots=True):
    """
    Determine if any GPUs are available
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    """
    Hyperparameter settings
    """
    lr = 2e-4
    bs = 64
    loss = nn.BCELoss()

    # Model
    G = Generator().to(device)
    D = Discriminator().to(device)

    G_optimizer = optim.Adam(G.parameters(), lr=lr, betas=(0.5, 0.999))
    D_optimizer = optim.Adam(D.parameters(), lr=lr, betas=(0.5, 0.999))

    # Load our data
    train_loader, _, _ = prepare_data(batch_size=bs)

    """
    Network training procedure
    Every step both the loss for disciminator and generator is updated
    Discriminator aims to classify reals and fakes
    Generator aims to generate bot accounts as realistic as possible
    """
    mean_D_loss = []
    mean_G_loss = []
    D_acc = []
    for epoch in range(epochs):
        acc = []
        epoch_D_loss = []
        epoch_G_loss = []

        for idx, (train_batch, _) in enumerate(train_loader):
            idx += 1

            # Training the discriminator
            # Real inputs are actual samples from the original dataset
            # Fake inputs are from the generator
            # Real inputs should be classified as 1 and fake as 0

            # Fetch a batch of real samples from training data
            # Feed real samples to Discriminator
            real_inputs = train_batch.to(device)
            real_outputs = D(real_inputs)
            real_label = torch.ones(real_inputs.shape[0], 1).to(device)

            # Make a batch of fake samples using Generator
            # Feed fake samples to Discriminator
            noise = (torch.rand(real_inputs.shape[0], 128) - 0.5) / 0.5
            noise = noise.to(device)
            fake_inputs = G(noise)
            fake_outputs = D(fake_inputs)
            fake_label = torch.zeros(fake_inputs.shape[0], 1).to(device)

            # Combine the two loss values
            # use combined loss to update Discriminator
            outputs = torch.cat((real_outputs, fake_outputs), 0)
            targets = torch.cat((real_label, fake_label), 0)

            # Just for evaluation and monitoring purposes
            predictions = outputs.cpu().detach().numpy()
            predictions = np.round(predictions)
            labels = targets.cpu().detach().numpy()

            D_loss = loss(outputs, targets)
            D_optimizer.zero_grad()
            D_loss.backward()
            D_optimizer.step()

            # Training the generator
            # For the Generator, the goal is to make the Discriminator believe everything is 1
            noise = (torch.rand(real_inputs.shape[0], 128) - 0.5) / 0.5
            noise = noise.to(device)

            # Make a batch of fake samples using Generator
            # Feed fake samples to Discriminator, compute reverse loss and use it to update the Generator
            fake_inputs = G(noise)
            fake_outputs = D(fake_inputs)
            fake_targets = torch.ones([fake_inputs.shape[0], 1]).to(device)
            G_loss = loss(fake_outputs, fake_targets)
            G_optimizer.zero_grad()
            G_loss.backward()
            G_optimizer.step()

            if idx % 100 == 0 or idx == len(train_loader):
                epoch_D_loss.append(D_loss.item())
                epoch_G_loss.append(G_loss.item())
                D_accuracy = accuracy_score(labels, predictions)
                acc.append(D_accuracy)

        print('Epoch {} -- Discriminator mean Accuracy: {:.5f}'.format(epoch, mean(acc)))
        print('Epoch {} -- Discriminator mean loss: {:.5f}'.format(epoch, mean(epoch_D_loss)))
        print('Epoch {} -- Generator mean loss: {:.5f}'.format(epoch, mean(epoch_G_loss)))
        print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~')
        mean_D_loss.append(mean(epoch_D_loss))
        mean_G_loss.append(mean(epoch_G_loss))
        D_acc.append(mean(acc))

    # loss plots
    plt.figure(figsize=(10, 7))
    plt.plot(mean_D_loss, color='blue', label='Discriminator loss')
    plt.plot(mean_G_loss, color='red', label='Generator loss')
    plt.xlabel('Epochs')
    plt.ylabel('Loss')
    plt.legend()
    plt.savefig('simple_gan/gan_loss.png')
    plt.show()

    plt.figure(figsize=(10, 7))
    plt.plot(D_acc, color='blue', label='Discriminator accuracy')
    plt.xlabel('Epochs')
    plt.ylabel('Accuracy')
    plt.legend()
    plt.savefig('simple_gan/discriminator_acc.png')
    plt.show()

    # Save Generator with the appropriate name
    if bots:
        torch.save(G, 'simple_gan/Bot_Generator_save.pth')
    else:
        torch.save(G, 'simple_gan/Human_Generator_save.pth')
    print('Generator saved.')


"""
A function that loads a trained Generator model and uses it to create synthetic samples
"""


def generate_synthetic_samples(num_of_samples=100, num_of_features=310, bots=True):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # Load initial data
    _, real_data, real_data_scaled = prepare_data(bots=bots)

    # Load the appropriate Generator
    if bots:
        generator = torch.load('simple_gan/Bot_Generator_save.pth')
    else:
        generator = torch.load('simple_gan/Human_Generator_save.pth')

    # Generate points in the latent space
    noise = (torch.rand(num_of_samples, 128) - 0.5) / 0.5
    noise = noise.to(device)

    # Pass latent points through our Generator to produce synthetic samples
    synthetic_samples = generator(noise)

    # Transform pytorch tensor to numpy array
    synthetic_samples = synthetic_samples.cpu().detach().numpy()
    synthetic_samples = synthetic_samples.reshape(num_of_samples, num_of_features)

    # Load saved min_max_scaler for inverse transformation of the generated data
    scaler = joblib.load("simple_gan/scaler.save")

    synthetic_data = scaler.inverse_transform(synthetic_samples)
    synthetic_data = pd.DataFrame(data=synthetic_data, columns=real_data.columns)

    synthetic_data = transform_bool.transform(synthetic_data)

    if bots:
        pickle.dump(synthetic_data, open('simple_gan/synthetic_bot_data_' + str(num_of_samples), 'wb'))
    else:
        pickle.dump(synthetic_data, open('simple_gan/synthetic_human_data_' + str(num_of_samples), 'wb'))

    return synthetic_data, real_data


def evaluate_synthetic_data(synthetic_data, real_data):

    ############# Statistical Metrics #############
    print('\n~~~~~~~~~ Statistical Metrics ~~~~~~~~~\n')

    """
    This metric uses the two-sample Kolmogorov–Smirnov test to compare the distributions of
    continuous columns using the empirical CDF. The output for each column is 1 minus the KS Test D statistic,
    which indicates the maximum distance between the expected CDF and the observed CDF values.
    """
    ks = KSTest.compute(synthetic_data, real_data)
    print('Inverted Kolmogorov-Smirnov D statistic: {}'.format(ks))

    ############# Likelihood Metrics #############
    print('\n~~~~~~~~~ Likelihood Metrics ~~~~~~~~~\n')
    """
        This metric fits a BayesianNetwork to the real data and 
        then evaluates the average likelihood of the rows from the synthetic data on it.
    """
    bnl_likelihood = BNLikelihood.compute(real_data, synthetic_data)
    print('\nBNLikelihood: {}'.format(BNLikelihood.normalize(bnl_likelihood)))

    """
        This metric fits a BayesianNetwork to the real data 
        and then evaluates the average log likelihood of the rows from the synthetic data on it.
    """
    bnl_log_likelihood = BNLogLikelihood.compute(real_data, synthetic_data)
    print('\nBNLogLikelihood: {}'.format((bnl_log_likelihood)))

    """
        This metric fits multiple GaussianMixture models to the real data 
        and then evaluates the average log likelihood of the synthetic data on them.
    """
    gm_log_likelihood = GMLogLikelihood.compute(real_data, synthetic_data, n_components=(1, 10), iterations=2)
    print('GMLogLikelihood: {}'.format(GMLogLikelihood.normalize(gm_log_likelihood)))

    ############# Detection Metrics #############
    print('\n~~~~~~~~~ Detection Metrics ~~~~~~~~~\n')
    """
        The output of the metrics will be the 1 minus 
        the average ROC AUC score across all the cross validation splits. 
        1 -> The classifier cannot distinguish real from synthetic data at all.
        0 -> The classifier is able to distinguish real from synthetic data with 100% accuracy.
    """
    log_detection_score = LogisticDetection.compute(real_data, synthetic_data)
    print('Logistic Detection score: {}'.format(log_detection_score))
    #svc_detection_score = SVCDetection.compute(real_data, synthetic_data)
    #print('Logistic Detection score: {}'.format(svc_detection_score))


    #kl_divergence = evaluate(synthetic_data, real_data, metrics=['ContinuousKLDivergence'])
    #print('Continuous Kullback–Leibler Divergence: {}'.format(kl_divergence))
    print(synthetic_data)


# train_gan(epochs=300, bots=False)
synthetic_data, real_data = generate_synthetic_samples(num_of_samples=30000, bots=True)
evaluate_synthetic_data(synthetic_data, real_data)
