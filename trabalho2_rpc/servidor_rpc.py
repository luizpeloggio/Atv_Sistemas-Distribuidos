from xmlrpc.server import SimpleXMLRPCServer
from socketserver import ThreadingMixIn
import threading
import time

HOST = '0.0.0.0'
PORT = 8000

class ServidorRPCThreading(ThreadingMixIn, SimpleXMLRPCServer):
    """Servidor XML-RPC multithread: cada requisição é atendida em sua própria thread."""
    daemon_threads = True

def calcular(a, b, operacao='soma'):
    """Operação 1: cálculo simples (rápido)."""
    print(f"[{threading.current_thread().name}] calcular({a}, {b}, '{operacao}')")
    if operacao == 'soma':
        return a + b
    elif operacao == 'subtracao':
        return a - b
    elif operacao == 'multiplicacao':
        return a * b
    elif operacao == 'divisao':
        return a / b if b != 0 else None
    return None

def processamento_demorado(segundos):
    """Operação 2: tarefa lenta, tempo controlado artificialmente."""
    print(f"[{threading.current_thread().name}] processamento_demorado({segundos}s) - INICIOU")
    time.sleep(segundos)
    print(f"[{threading.current_thread().name}] processamento_demorado({segundos}s) - CONCLUIU")
    return f"Processamento de {segundos} segundos concluido"

def processar_colecao(valores, operacao='media'):
    """Operação 3: processa uma coleção de valores (tempo intermediário)."""
    print(f"[{threading.current_thread().name}] processar_colecao({valores}, '{operacao}')")
    time.sleep(2)
    if not valores:
        return None
    if operacao == 'media':
        return sum(valores) / len(valores)
    elif operacao == 'maior':
        return max(valores)
    elif operacao == 'menor':
        return min(valores)
    elif operacao == 'soma':
        return sum(valores)
    return None

def iniciar_servidor():
    servidor = ServidorRPCThreading((HOST, PORT), allow_none=True, logRequests=False)
    servidor.register_function(calcular, 'calcular')
    servidor.register_function(processamento_demorado, 'processamento_demorado')
    servidor.register_function(processar_colecao, 'processar_colecao')
    print(f"[SERVIDOR RPC] Multithread ouvindo em {HOST}:{PORT}")
    print("Operacoes disponiveis: calcular, processamento_demorado, processar_colecao\n")
    servidor.serve_forever()

if __name__ == '__main__':
    iniciar_servidor()
