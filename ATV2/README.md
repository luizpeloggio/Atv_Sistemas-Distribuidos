# Trabalho 2 — RPC Síncrono e Assíncrono com Servidor Multithread

Disciplina: Sistemas Distribuídos
Integrantes: [NOME 1] e [NOME 2]
Vídeo de demonstração: [LINK DO VÍDEO]

## 1. Visão geral

Ambiente virtualizado no VirtualBox com 3 VMs Debian 13, simulando uma arquitetura corporativa básica com zona protegida. Sobre ele, um serviço RPC (XML-RPC em Python) com três operações remotas de tempos de processamento diferentes, consumido por clientes **síncronos** e **assíncronos**.

```
[Internet] -- NAT (enp0s3) -- VM1 (Gateway/DHCP/Servidor RPC) -- Rede Interna "redeB" (enp0s8) -- VM2 e VM3 (clientes)
```

| VM | Função | Rede |
|---|---|---|
| VM1 | Roteador/NAT, servidor DHCP, servidor RPC multithread | enp0s3 (NAT, Rede A) e enp0s8 (192.168.10.1, Rede B) |
| VM2 | Cliente RPC 1 | Rede B, IP via DHCP (192.168.10.100) |
| VM3 | Cliente RPC 2 | Rede B, IP via DHCP (192.168.10.101) |

## 2. Configuração da infraestrutura (VM1)

```bash
# IP fixo da interface interna
printf 'auto enp0s8\niface enp0s8 inet static\n    address 192.168.10.1\n    netmask 255.255.255.0\n' | sudo tee /etc/network/interfaces.d/enp0s8
sudo ifup enp0s8

# Encaminhamento de pacotes
echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# NAT
sudo apt install iptables -y
sudo iptables -t nat -A POSTROUTING -o enp0s3 -j MASQUERADE
sudo iptables -A FORWARD -i enp0s8 -o enp0s3 -j ACCEPT
sudo iptables -A FORWARD -i enp0s3 -o enp0s8 -m state --state RELATED,ESTABLISHED -j ACCEPT

# DHCP
sudo apt install isc-dhcp-server -y
printf 'subnet 192.168.10.0 netmask 255.255.255.0 {\n  range 192.168.10.100 192.168.10.200;\n  option routers 192.168.10.1;\n  option domain-name-servers 8.8.8.8, 8.8.4.4;\n}\n' | sudo tee -a /etc/dhcp/dhcpd.conf
printf 'INTERFACESv4="enp0s8"\n' | sudo tee /etc/default/isc-dhcp-server
sudo systemctl restart isc-dhcp-server
```

VM2 e VM3 usam um único adaptador em Rede Interna (`redeB`) e recebem IP por DHCP. Testes realizados: `ping 192.168.10.1` (gateway), `ping 8.8.8.8` (internet via NAT) e ping entre VM2 e VM3, todos com 0% de perda.

> Observação: no host Linux foi necessário descarregar o KVM antes de iniciar as VMs (`sudo modprobe -r kvm_intel && sudo modprobe -r kvm`), pois ele conflita com o VT-x do VirtualBox.

## 3. Arquivos

| Arquivo | Onde roda | Descrição |
|---|---|---|
| `servidor_rpc.py` | VM1 | Servidor XML-RPC multithread (uma thread por requisição), porta 8000 |
| `cliente_rpc_sincrono.py` | VM2 e VM3 | Cliente com chamadas bloqueantes e log de horários |
| `cliente_rpc_assincrono.py` | VM2 e VM3 | Cliente com chamadas via `Future` e atividades locais em paralelo |

Operações remotas do servidor:
1. `calcular(a, b, operacao)`: cálculo simples e rápido.
2. `processamento_demorado(segundos)`: tarefa lenta com tempo controlado por `time.sleep()` (5, 10 s ou mais).
3. `processar_colecao(valores, operacao)`: média, maior, menor ou soma de uma lista (aprox. 2 s).

## 4. Como executar

Requisitos: Python 3 (já vem no Debian 13). Nenhuma biblioteca externa é necessária.

```bash
# VM1
python3 servidor_rpc.py

# VM2 e VM3 - Parte I (síncrono)
python3 cliente_rpc_sincrono.py

# VM2 e VM3 - Parte II (assíncrono)
python3 cliente_rpc_assincrono.py
```

O mesmo servidor atende as duas partes: o comportamento síncrono ou assíncrono é definido pelo cliente. Para observar a concorrência, execute os clientes de VM2 e VM3 ao mesmo tempo e acompanhe as threads nos logs do servidor.

## 5. Resultados observados

[COLE AQUI UM TRECHO DOS LOGS REAIS: cliente síncrono, cliente assíncrono e servidor]

## 6. Perguntas de comparação

**Qual foi a principal diferença observada entre RPC síncrona e RPC assíncrona?**
Na síncrona, o cliente ficou parado entre o envio e a resposta, sem executar mais nada. Na assíncrona, o cliente continuou executando atividades locais enquanto a resposta não chegava e só bloqueou no `future.result()`, quando o resultado foi necessário.

**O que aconteceu com o Cliente 1 enquanto aguardava uma chamada síncrona de 10 segundos?**
Ficou bloqueado: nenhuma outra instrução foi executada até a resposta chegar.

**O que o cliente conseguiu realizar durante uma chamada assíncrona?**
Executou outras atividades locais (atividade local 1 e 2) enquanto o servidor processava a operação de 10 segundos.

**Qual é a vantagem de utilizar um servidor multithread neste cenário?**
Cada requisição é tratada em sua própria thread. Uma operação longa de um cliente não impede o atendimento do outro, e as chamadas de VM2 e VM3 avançam juntas.

**O que aconteceria se o servidor possuísse apenas uma thread e recebesse simultaneamente uma operação de 10 segundos e outra de 5 segundos?**
As requisições seriam atendidas em fila. Se a de 10 s entrasse primeiro, a de 5 s esperaria 10 s e terminaria só aos 15 s, em vez dos 5 s que levaria atendida de forma independente.

**RPC assíncrona necessariamente torna o processamento realizado pelo servidor mais rápido? Justifique.**
Não. A assincronicidade só muda o que o cliente faz enquanto espera. O servidor leva o mesmo tempo para processar a operação. O ganho é de aproveitamento do tempo do cliente, não de velocidade do servidor.

**Qual é a diferença entre assincronicidade no cliente e concorrência no servidor?**
Assincronicidade no cliente é não bloquear enquanto aguarda a resposta. Concorrência no servidor é atender várias requisições ao mesmo tempo (aqui, com threads). São independentes: um cliente assíncrono pode falar com um servidor de thread única, e clientes síncronos se beneficiam de um servidor concorrente quando são vários.

**As duas chamadas RPC foram realmente executadas simultaneamente ou concorrentemente? Explique considerando o ambiente utilizado.**
Concorrentemente. O servidor roda em Python (CPython), cujo GIL permite que só uma thread execute bytecode por vez. As threads avançam de forma intercalada, principalmente porque `time.sleep()` e operações de rede liberam o GIL. Além disso, as VMs têm poucos núcleos virtuais, então não há paralelismo garantido. Como as operações são dominadas por espera, o efeito observado é de atendimento simultâneo.
