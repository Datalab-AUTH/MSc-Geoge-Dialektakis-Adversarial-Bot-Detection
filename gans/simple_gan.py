"""
Import necessary libraries to create a generative adversarial network
The code is developed using the PyTorch library
"""
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
from sdv.evaluation import evaluate

from statistics import mean

"""
Network Architectures
The following are the discriminator and generator architectures
"""


class Discriminator(nn.Module):
    def __init__(self):
        super(Discriminator, self).__init__()
        self.fc1 = nn.Linear(310, 512)
        self.fc2 = nn.Linear(512, 1)
        self.activation = nn.LeakyReLU(0.1)

    def forward(self, x):
        x = x.view(-1, 310)
        x = self.activation(self.fc1(x))
        x = self.fc2(x)
        return nn.Sigmoid()(x)


class Generator(nn.Module):
    def __init__(self):
        super(Generator, self).__init__()
        self.fc1 = nn.Linear(128, 1024)
        self.fc2 = nn.Linear(1024, 2048)
        self.fc3 = nn.Linear(2048, 310)
        self.activation = nn.ReLU()

    def forward(self, x):
        x = self.activation(self.fc1(x))
        x = self.activation(self.fc2(x))
        x = self.fc3(x)
        x = x.view(-1, 1, 1, 310)
        return nn.Tanh()(x)


def prepare_data(data, batch_size):
    df = pd.DataFrame(data)
    # Convert labels from string to 0 and 1
    df['label'] = df['label'].map({'human': 0, 'bot': 1, 'cyborg': 1})
    # Convert features that are boolean to integers
    df = df.applymap(lambda x: int(x) if isinstance(x, bool) else x)

    # keep only bot accounts to train our GAN
    bots_df = df[df['label'] == 1]
    y = bots_df['label']

    # Drop unwanted columns
    bots_df = bots_df.drop(['user_name', 'user_screen_name', 'user_id', 'label'], axis=1)
    if 'max_appearance_of_punc_mark' in bots_df.columns:
        bots_df = bots_df.drop(['max_appearance_of_punc_mark'], axis=1)

    # Scale our data in the range of (0, 1)
    scaler = MinMaxScaler()
    df_scaled = scaler.fit_transform(X=bots_df)

    # Store scaler for later use
    scaler_filename = "scaler.save"
    joblib.dump(scaler, scaler_filename)

    # Transform dataframe into pytorch Tensor
    train = TensorDataset(torch.Tensor(df_scaled), torch.Tensor(np.array(y)))
    train_loader = DataLoader(dataset=train, batch_size=batch_size, shuffle=True)
    return train_loader, bots_df


def train_gan():
    """
    Determine if any GPUs are available
    """
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    """
    Hyperparameter settings
    """
    epochs = 150
    lr = 2e-4
    bs = 64
    loss = nn.BCELoss()

    # Model
    G = Generator().to(device)
    D = Discriminator().to(device)

    G_optimizer = optim.Adam(G.parameters(), lr=lr, betas=(0.5, 0.999))
    D_optimizer = optim.Adam(D.parameters(), lr=lr, betas=(0.5, 0.999))

    # Load our data
    bot_data = pickle.load(open('final_data_no_rts_v2', 'rb'))
    train_loader, train_df = prepare_data(bot_data, batch_size=bs)

    """
    Network training procedure
    Every step both the loss for disciminator and generator is updated
    Discriminator aims to classify reals and fakes
    Generator aims to generate bot accounts as realistic as possible
    """
    for epoch in range(epochs):
        acc = []
        mean_D_loss = []
        mean_G_loss = []
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

            # Just for evaluation and print purposes
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
                # print('Epoch {} - Iteration {}: discriminator_loss {:.4f} generator_loss {:.4f}'.format(epoch, idx, D_loss.item(), G_loss.item()))

                mean_D_loss.append(D_loss.item())
                mean_G_loss.append(G_loss.item())
                D_accuracy = accuracy_score(labels, predictions)
                acc.append(D_accuracy)

        print('Epoch {} -- Discriminator mean Accuracy: {:.5f}'.format(epoch, mean(acc)))
        print('Epoch {} -- Discriminator mean loss: {:.5f}'.format(epoch, mean(mean_D_loss)))
        print('Epoch {} -- Generator mean loss: {:.5f}'.format(epoch, mean(mean_G_loss)))
        print('~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~')

    torch.save(G, 'Generator_save.pth')
    print('Generator saved.')
    return train_df


"""
A function that loads a trained Generator model and uses it to create synthetic samples
"""


def generate_synthetic_samples(num_of_samples=100, num_of_features=310):
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    generator = torch.load('Generator_save.pth')
    # Generate points in the latent space
    noise = (torch.rand(num_of_samples, 128) - 0.5) / 0.5
    noise = noise.to(device)

    # Pass latent points through our Generator to produce synthetic samples
    synthetic_samples = generator(noise)

    # Transform pytorch tensor to numpy array
    synthetic_samples = synthetic_samples.cpu().detach().numpy()
    synthetic_samples = synthetic_samples.reshape(num_of_samples, num_of_features)

    # Load saved min_max_scaler for inverse transformation of the generated data
    scaler = joblib.load("scaler.save")
    synthetic_data = scaler.inverse_transform(synthetic_samples)
    return synthetic_data


real_data = train_gan()

synthetic_data = generate_synthetic_samples(num_of_samples=248)
synthetic_data = pd.DataFrame(synthetic_data)
print('Data evaluation: {}'.format(evaluate(synthetic_data, real_data)))
print(synthetic_data)