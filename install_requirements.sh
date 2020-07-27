#!/bin/bash

echo -e "\e[32mInstalling AWS CLI Version 2\e[0m"
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

echo -e "\e[32mInstalling kubectl\e[0m"
curl -o kubectl "https://amazon-eks.s3.us-west-2.amazonaws.com/1.15.10/2020-02-22/bin/linux/amd64/kubectl"
chmod +x ./kubectl
mkdir -p $HOME/bin && cp ./kubectl $HOME/bin/kubectl && export PATH=$PATH:$HOME/bin
echo 'export PATH=$PATH:$HOME/bin' >> ~/.bash_profile

echo -e "\e[32mInstalling eksctl\e[0m"
curl --location "https://github.com/weaveworks/eksctl/releases/latest/download/eksctl_$(uname -s)_amd64.tar.gz" | tar xz -C /tmp
sudo mv /tmp/eksctl /usr/local/bin

echo -e "\e[32mInstalling docker-compose\e[0m"
sudo curl -L "https://github.com/docker/compose/releases/download/1.25.5/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
sudo ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose

echo -e "\e[32mInstalling helm\e[0m"
curl https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 > get_helm.sh
chmod 700 get_helm.sh
./get_helm.sh

echo -e "\e[32mInstalling jq\e[0m"
sudo yum install jq -y

echo -e "\n\n\e[43mConfirm the installs\e[0m"
echo -e "\e[32mAWS CLI Version 2\e[0m"
aws --version
echo -e "\n\e[32mkubectl\e[0m"
kubectl version --short --client
echo -e "\n\e[32meksctl\e[0m"
eksctl version
echo -e "\n\e[32mdocker\e[0m"
docker --version
echo -e "\n\e[32mdocker-compose\e[0m"
docker-compose --version
echo -e "\n\e[32mhelm\e[0m"
helm version --short
echo -e "\n\e[32mjq\e[0m"
jq --version