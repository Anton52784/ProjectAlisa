from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
import requests

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///skill_database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class UserConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    yandex_id = db.Column(db.String(100), unique=True)
    provider = db.Column(db.String(50), default='')
    api_key = db.Column(db.String(200), default='')
    model_name = db.Column(db.String(100), default='')
    step = db.Column(db.String(50), default='normal')

    def __init__(self, yandex_id, provider='', api_key='', model_name='', step='normal'):
        self.yandex_id = yandex_id
        self.provider = provider
        self.api_key = api_key
        self.model_name = model_name
        self.step = step

class MessageHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    yandex_id = db.Column(db.String(100))
    text = db.Column(db.String(500))

    def __init__(self, yandex_id, text):
        self.yandex_id = yandex_id
        self.text = text

with app.app_context():
    db.create_all()

def ask_ai(provider, api_key, model, text, history):
    try:
        if provider == 'deepseek':
            headers = {"Authorization": f"Bearer {api_key}"}
            messages = [{"role": "system", "content": "Ты полезный ассистент."}]
            for h in history:
                messages.append({"role": "user", "content": h["user"]})
                messages.append({"role": "assistant", "content": h["bot"]})
            messages.append({"role": "user", "content": text})
            
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                json={"model": model, "messages": messages},
                headers=headers
            ).json()
            return response['choices'][0]['message']['content']

        elif provider == 'gemini':
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            contents = []
            for h in history:
                contents.append({"role": "user", "parts": [{"text": h["user"]}]})
                contents.append({"role": "model", "parts": [{"text": h["bot"]}]})
            contents.append({"role": "user", "parts": [{"text": text}]})
            
            response = requests.post(url, json={"contents": contents}).json()
            return response['candidates'][0]['content']['parts'][0]['text']
            
        return "❌ Неизвестный провайдер."
    except Exception as e:
        return f"❌ Ошибка при запросе: {str(e)}"

def make_alice_response(text, image_id=None, session_state=None):
    response_data = {"text": text, "tts": text}
    if image_id:
        response_data["card"] = {
            "type": "BigImage",
            "image_id": image_id,
            "title": "Привет!",
            "description": text
        }
    return jsonify({
        "response": response_data,
        "session_state": session_state or {},
        "version": "1.0"
    })

@app.route('/alice', methods=['POST'])
def alice_webhook():
    data = request.json
    if not data:
        return jsonify({"error": "❌❌❌ Нет данных. Сервер ждёт данные от Алисы."})
        
    user_id = data['session']['application']['application_id']
    user_text = data['request']['original_utterance'].lower().strip()
    is_new = data['session']['new']
    
    state = data.get('state', {}).get('session', {})
    history = state.get('history', [])

    user_db = UserConfig.query.filter_by(yandex_id=user_id).first()
    if not user_db:
        user_db = UserConfig(yandex_id=user_id)
        db.session.add(user_db)
        db.session.commit()

    if is_new:
        greeting = "Привет! Я навык, использующий нейросети. Напиши /config чтобы настроить меня."
        image_id = "1030494/2a7140fed83b7fb9dbdb" 
        return make_alice_response(greeting, image_id=image_id, session_state={"history": []})

    if user_text == '/stop':
        user_db.step = 'normal'
        db.session.commit()
        return make_alice_response("✅ Остановлено. История диалога очищена.", session_state={"history": []})

    if user_text == '/history':
        msgs = MessageHistory.query.filter_by(yandex_id=user_id).order_by(MessageHistory.id.desc()).limit(3).all()
        if not msgs:
            return make_alice_response("История пуста.", session_state={"history": history})
        resp = "Последние запросы: " + " | ".join([m.text for m in msgs])
        return make_alice_response(resp, session_state={"history": history})

    if user_text == '/config':
        user_db.step = 'wait_provider'
        db.session.commit()
        return make_alice_response("Напиши провайдера: gemini или deepseek.")

    if user_db.step == 'wait_provider':
        user_db.provider = user_text
        user_db.step = 'wait_key'
        db.session.commit()
        return make_alice_response("✅ Отлично. Теперь отправь мне API-ключ.")
        
    elif user_db.step == 'wait_key':
        user_db.api_key = data['request']['original_utterance']
        user_db.step = 'wait_model'
        db.session.commit()
        return make_alice_response("✅ Введи точное название модели. Узнать список моделей можно в документации провайдера.")
        
    elif user_db.step == 'wait_model':
        user_db.model_name = data['request']['original_utterance']
        user_db.step = 'normal'
        db.session.commit()
        return make_alice_response("✅ Настройка завершена! Можешь задавать вопросы.")

    if user_db.step == 'normal':
        if not user_db.provider or not user_db.api_key or not user_db.model_name:
            return make_alice_response("❌ У вас не настроена нейросеть. Напишите /config.", session_state={"history": history})
        
        answer = ask_ai(user_db.provider, user_db.api_key, user_db.model_name, user_text, history)
        
        new_msg = MessageHistory(yandex_id=user_id, text=user_text)
        db.session.add(new_msg)
        db.session.commit()
        
        history.append({"user": user_text, "bot": answer})
        history = history[-5:]
        
        return make_alice_response(answer, session_state={"history": history})

    return make_alice_response("❌ Команда не распознана.", session_state={"history": history})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
