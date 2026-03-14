import requests, os

# Puxa a chave que você salvou no Render
API_KEY_IA = os.environ.get("API_KEY_IA")

def listar_modelos():
    print("🔍 Iniciando busca de modelos disponíveis...")
    
    # URL oficial do Google para listar modelos
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY_IA}"
    
    try:
        response = requests.get(url, timeout=30)
        data = response.json()
        
        if response.status_code == 200:
            print("✅ Conexão bem-sucedida! Modelos disponíveis:")
            for model in data.get('models', []):
                # Filtra apenas modelos que suportam geração de conteúdo
                if 'generateContent' in model.get('supportedGenerationMethods', []):
                    print(f"👉 Nome para usar no código: {model['name'].split('/')[-1]}")
                    print(f"   Descrição: {model['description']}\n")
        else:
            print(f"❌ Erro {response.status_code}: {data.get('error', {}).get('message', 'Erro desconhecido')}")
            
    except Exception as e:
        print(f"❌ Erro de conexão: {e}")

if __name__ == "__main__":
    listar_modelos()
