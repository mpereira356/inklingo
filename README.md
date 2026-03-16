# Inklingo - Leia livros reais. Entenda cada palavra.

Uma aplicação web moderna e elegante construída com Flask para ajudar usuários a aprender inglês enquanto leem seus livros favoritos em PDF.

## 🚀 Funcionalidades

- **Autenticação de Usuário**: Registro e login seguros.
- **Upload de Livros**: Envie seus livros em formato PDF.
- **Leitor Inteligente**: Interface focada na leitura com navegação por páginas.
- **Interação com Palavras**: Clique em qualquer palavra para ver a tradução instantânea.
- **Pronúncia**: Ouça a pronúncia correta da palavra selecionada.
- **Teste de Pronúncia**: Use o microfone para praticar sua fala e receba feedback em tempo real.
- **Vocabulário Diário**: Salve até 10 palavras por dia para estudar depois.
- **Progresso de Leitura**: O sistema salva automaticamente onde você parou.

## 🛠️ Tecnologias Utilizadas

- **Backend**: Python, Flask, SQLite, SQLAlchemy, Flask-Login.
- **Frontend**: HTML5, TailwindCSS (via CDN), JavaScript Vanilla.
- **Bibliotecas**: PyMuPDF (extração de texto), Web Speech API (voz e reconhecimento).

## 📋 Como Executar

1. **Instale as dependências**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Inicie a aplicação**:
   ```bash
   python app.py
   ```

3. **Acesse no navegador**:
   Abra `http://localhost:5000`

## 📂 Estrutura do Projeto

- `app.py`: Servidor Flask e rotas da aplicação.
- `models.py`: Definições do banco de dados.
- `templates/`: Arquivos HTML (Base, Login, Dashboard, Leitor).
- `static/`: Arquivos CSS, JS e uploads de livros.
- `requirements.txt`: Lista de dependências Python.

---
Desenvolvido para proporcionar a melhor experiência de aprendizado de idiomas.
