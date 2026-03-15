import telebot, requests, os, time, urllib.parse
from telebot import types
from flask import Flask
from threading import Thread

# --- 1. CONFIGURAÇÃO DO SERVIDOR WEB PARA O RENDER ---
app = Flask('')
@app.route('/')
def home(): 
    return "MestreFisio V5 Online - Sistema Visual e Anti-Sono Ativado"

def run():
    # O Render usa a porta 10000 por padrão
    app.run(host='0.0.0.0', port=10000)

# --- 2. TRUQUE ANTI-SONO (KEEP ALIVE) ---
def keep_alive():
    url_do_seu_bot = "https://fisio-ia-bot.onrender.com" 
    while True:
        try:
            requests.get(url_do_seu_bot)
            print("⚓ Ping preventivo: Servidor acordado!")
        except:
            print("⚠️ Falha no ping preventivo.")
        time.sleep(600) # Ping a cada 10 minutos

# --- 3. CONFIGURAÇÕES INICIAIS ---
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM")
API_KEY_IA = os.environ.get("API_KEY_IA")
MODELO = "gemini-2.5-flash"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=True)

# Menu Principal com Botões
def menu_principal():
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_paciente = types.InlineKeyboardButton("👤 Analisar Novo Paciente", callback_data="novo_paciente")
    btn_duvida = types.InlineKeyboardButton("📚 Dúvida Técnica Direta", callback_data="duvida_tecnica")
    markup.add(btn_paciente, btn_duvida)
    return markup

# --- 4. FUNÇÃO DE GERAÇÃO DE IMAGEM (POLLINATIONS) ---
def enviar_ilustracao(chat_id, termo_fisioterapia):
    # Criamos um prompt técnico em inglês para maior precisão da IA
    # 'no text' ajuda a evitar palavras erradas na imagem
    prompt_formatado = f"Medical atlas illustration of {termo_fisioterapia}, high detail, anatomical precision, white background, no text, professional clinical style"
    prompt_url = urllib.parse.quote(prompt_formatado)
    
    # URL da Pollinations (Grátis e sem chave)
    url_imagem = f"https://pollinations.ai/p/{prompt_url}?width=1024&height=1024&seed=42&model=flux"
    
    try:
        # Enviamos a foto com a legenda em PORTUGUÊS
        bot.send_photo(
            chat_id, 
            url_imagem, 
            caption=f"📸 **Referência Visual: {termo_fisioterapia.upper()}**\n\n_Nota: Ilustração técnica gerada para auxílio didático._"
        )
    except Exception as e:
        print(f"Erro ao enviar imagem: {e}")

# --- 5. TRATAMENTO DE MENSAGENS E BOTÕES ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.send_message(
        message.chat.id, 
        "🚀 **MestreFisio IA Ativo!**\nSua inteligência clínica com suporte visual.\n\nEscolha uma opção:", 
        reply_markup=menu_principal(), 
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    bot.answer_callback_query(call.id)
    if call.data == "novo_paciente":
        msg = bot.send_message(call.message.chat.id, "📝 Digite o **NOME** do paciente:")
        bot.register_next_step_handler(msg, obter_nome_paciente)
    elif call.data == "duvida_tecnica":
        msg = bot.send_message(call.message.chat.id, "💡 Digite sua dúvida técnica (ex: exercícios para manguito):")
        bot.register_next_step_handler(msg, processar_ia_direta)

def obter_nome_paciente(message):
    nome = message.text.upper().strip()
    msg = bot.send_message(message.chat.id, f"✅ Paciente: **{nome}**\n\nAgora, descreva o quadro clínico:")
    bot.register_next_step_handler(msg, processar_ia_paciente, nome)

# --- 6. INTEGRAÇÃO COM GEMINI 2.5 FLASH ---
def processar_ia_paciente(message, nome):
    prompt = (f"Atue como um fisioterapeuta PhD. Analise o caso de {nome}: {message.text}. "
              "Estruture em: 1. Hipóteses, 2. Testes Sugeridos, 3. Conduta. "
              "Ao final da resposta, adicione OBRIGATORIAMENTE uma linha assim: 'IMAGEM: [termo técnico do principal músculo ou teste em inglês]'")
    chamar_gemini(message, prompt)

def processar_ia_direta(message):
    prompt = (f"Responda como um fisioterapeuta PhD de forma técnica: {message.text}. "
              "Ao final da resposta, adicione OBRIGATORIAMENTE uma linha assim: 'IMAGEM: [termo principal do assunto em inglês]'")
    chamar_gemini(message, prompt)

def chamar_gemini(message, prompt):
    aguarde = bot.send_message(message.chat.id, "🧠 Processando análise clínica...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODELO}:generateContent?key={API_KEY_IA}"
    
    try:
        response = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60)
        res_json = response.json()
        analise_completa = res_json['candidates'][0]['content']['parts'][0]['text']
        
        bot.delete_message(message.chat.id, aguarde.message_id)
        
        # Separar o texto clínico da instrução de imagem
        partes = analise_completa.split("IMAGEM:")
        texto_clinico = partes[0].strip()
        
        # Enviar o texto (lidando com limite de caracteres do Telegram)
        if len(texto_clinico) > 4000:
            for i in range(0, len(texto_clinico), 4000):
                bot.send_message(message.chat.id, texto_clinico[i:i+4000])
        else:
            bot.send_message(message.chat.id, texto_clinico)
        
        # Disparar a geração de imagem se houver o comando
        if len(partes) > 1:
            termo_imagem = partes[1].replace("[", "").replace("]", "").strip()
            enviar_ilustracao(message.chat.id, termo_imagem)
        
        # Reexibir menu
        bot.send_message(message.chat.id, "O que deseja fazer agora?", reply_markup=menu_principal())
            
    except Exception as e:
        bot.send_message(message.chat.id, "❌ Erro na consulta. Tente novamente.", reply_markup=menu_principal())
        print(f"Erro Gemini: {e}")

# --- 7. INICIALIZAÇÃO ---
if __name__ == "__main__":
    Thread(target=run).start()
    Thread(target=keep_alive).start()
    bot.remove_webhook()
    print("🤖 MestreFisio V5 Iniciado!")
    bot.infinity_polling(timeout=20, long_polling_timeout=5)
        
