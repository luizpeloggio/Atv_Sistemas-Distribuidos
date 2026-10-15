import xmlrpc.client
import datetime
import time
from concurrent.futures import ThreadPoolExecutor

SERVIDOR = 'http://192.168.10.1:8000'

def log(msg):
    agora = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"{agora} - {msg}")

def chamar_processamento_demorado(segundos):
    proxy = xmlrpc.client.ServerProxy(SERVIDOR, allow_none=True)
    return proxy.processamento_demorado(segundos)

def executar_atividade_local(numero):
    log(f"Executando atividade local {numero}")
    time.sleep(2)

def main():
    print("=== CLIENTE RPC ASSINCRONO ===\n")
    executor = ThreadPoolExecutor(max_workers=4)

    log("Requisicao assincrona enviada")
    future = executor.submit(chamar_processamento_demorado, 10)
    log("Cliente continuou sua execucao")

    executar_atividade_local(1)
    executar_atividade_local(2)

    resultado = future.result()  # só bloqueia aqui, quando o resultado é realmente necessário
    log("Resultado RPC disponivel")
    log(f"Resultado: {resultado}")

    executor.shutdown()

if __name__ == '__main__':
    main()
