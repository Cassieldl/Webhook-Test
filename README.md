# Webhook Monitor

Ferramenta para receber, registrar e auditar webhooks de notas fiscais.
Hospedável na nuvem via Railway — gratuito, acessível por qualquer pessoa da equipe.

---

## Rodar localmente (teste rápido)

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
Acesse: http://localhost:8000

---

## Hospedar no Railway (para toda a equipe)

### Pré-requisito
Ter uma conta em https://railway.app (gratuito)

### Passo a passo

**1. Instale o Git** (se não tiver)
https://git-scm.com/downloads

**2. Crie um repositório no GitHub**
- Acesse https://github.com/new
- Crie um repositório privado (ex: `webhook-monitor`)
- Siga as instruções para fazer o upload desta pasta

**3. No Railway**
- Acesse https://railway.app
- Clique em "New Project" → "Deploy from GitHub repo"
- Selecione o repositório criado
- O Railway detecta automaticamente o Python e sobe o servidor

**4. URL pública**
- Após o deploy, clique em "Settings" → "Generate Domain"
- Você receberá uma URL como: `https://webhook-monitor-production.up.railway.app`
- Compartilhe com a equipe — todos podem acessar o dashboard

**5. Configure o endpoint no seu sistema**
```
POST https://SUA-URL.up.railway.app/webhook?lote=NOME_DO_LOTE
```

---

## Endpoints

| Método | Rota           | O que faz                              |
|--------|----------------|----------------------------------------|
| POST   | /webhook       | Recebe e registra o webhook            |
| GET    | /              | Dashboard visual                       |
| GET    | /webhook/{id}  | Detalhes de um registro específico     |
| DELETE | /webhooks      | Apaga todos os registros + libera disco|
| GET    | /stats         | Contagem total e último recebido       |

---

## Identificar o lote

Via URL (recomendado):
```
POST /webhook?lote=Lote_Novembro_01
```

Via header HTTP:
```
X-Lote: Lote_Novembro_01
```

---

## Observações

- O banco SQLite é local no servidor Railway — ao fazer novo deploy, os dados são apagados.
  Para persistência longa, considere adicionar um banco PostgreSQL pelo Railway (gratuito).
- O IP real é capturado via X-Forwarded-For (funciona atrás de proxy/Railway automaticamente).
- A localização geográfica é consultada via ip-api.com (gratuito, sem chave necessária).
