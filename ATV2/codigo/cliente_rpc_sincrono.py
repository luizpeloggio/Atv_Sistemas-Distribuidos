import xmlrpc.client
import datetime

SERVIDOR = 'http://192.168.10.1:8000'

def log(msg):
    agora = datetime.datetime.now().strftime('%H:%M:%S')
    print(f"{agora} - {msg}")

def chamada_sincrona(proxy, nome_operacao, func_chamada):
    log("Enviando requisicao RPC")
    log(f"Operacao solicitada: {nome_operacao}")
    inicio = datetime.datetime.now()

    resultado = func_chamada()

    fim = datetime.datetime.now()
    log("Resposta recebida")
    log(f"Resultado: {resultado}")
    log(f"Tempo total: {(fim - inicio).total_seconds():.1f} segundos\n")
    return resultado

def main():
    proxy = xmlrpc.client.ServerProxy(SERVIDOR, allow_none=True)
    print("=== CLIENTE RPC SINCRONO ===\n")

    chamada_sincrona(
        proxy, "calcular(10, 5, 'soma')",
        lambda: proxy.calcular(10, 5, 'soma')
    )

    chamada_sincrona(
        proxy, "processamento_demorado(10)",
        lambda: proxy.processamento_demorado(10)
    )

    valores = [4, 8, 15, 16, 23, 42]
    chamada_sincrona(
        proxy, f"processar_colecao({valores}, 'media')",
        lambda: proxy.processar_colecao(valores, 'media')
    )

if __name__ == '__main__':
    main()
