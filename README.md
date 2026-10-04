# Dockseal — Backend

API em FastAPI da **Dockseal: Plataforma Inteligente de Conformidade Portuária** (TCC — Ciência da Computação, UNIP Santos).

O ponto central é um agente de IA (Agno + OpenAI) que lê um ou mais documentos portuários (Bill of Lading, Manifesto de Carga, Nota Fiscal, Ordem de Carregamento) e aponta as divergências entre eles. Por exemplo, um documento diz 2 toneladas e outro diz 10 toneladas. Para cada divergência, ele devolve uma sugestão de correção.

> O agente **apenas lê e recomenda**. Ele nunca altera os documentos.

> **Time de front-end:** o guia completo para consumir a API (endpoints, tipos TypeScript, erros e um client pronto) está em **[docs/API.md](docs/API.md)**.

## Sumário

- [Tecnologias](#tecnologias)
- [Pré-requisitos](#pré-requisitos)
- [Configuração](#configuração)
- [Rodando a aplicação](#rodando-a-aplicação)
- [Perfis e permissões](#perfis-e-permissões)
- [Usando a API](#usando-a-api)
  - [Pelo navegador (Swagger)](#pelo-navegador-swagger)
  - [Login](#1-login)
  - [Análise de documentos](#2-análise-de-documentos-post-analysis)
  - [Fluxo completo com embarque](#3-fluxo-completo-com-embarque)
  - [Alertas e histórico](#4-alertas-e-histórico)
- [Referência de endpoints](#referência-de-endpoints)
- [Formato da resposta da análise](#formato-da-resposta-da-análise)
- [Erros comuns](#erros-comuns)
- [Testes](#testes)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Modelo de dados](#modelo-de-dados)

## Tecnologias

| Camada | Tecnologia |
|---|---|
| API | FastAPI (Python 3.13) |
| Agente de IA | [Agno](https://docs.agno.com) com modelo da OpenAI (`gpt-4.1-mini`) |
| OCR | Modelo de visão da OpenAI (`gpt-4.1`) para imagens, PDFs digitalizados e formulários preenchidos |
| Banco de dados | SQLAlchemy 2 (SQLite por padrão; PostgreSQL opcional) |
| Autenticação | JWT (PyJWT) + hash de senha Argon2 (pwdlib) |
| Leitura de arquivos | pypdf (texto de PDF), pypdfium2 + Pillow (renderização para OCR) e python-docx (DOCX) |
| Gerenciador de pacotes | [uv](https://docs.astral.sh/uv/) |

## Pré-requisitos

- Python 3.13
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Uma chave de API da OpenAI, gerada em https://platform.openai.com/api-keys (a conta precisa ter créditos).

## Configuração

**1. Criar o arquivo `.env`** a partir do exemplo:

```bash
cp .env.example .env
```

**2. Preencher as variáveis:**

| Variável | Obrigatória | Descrição | Padrão |
|---|---|---|---|
| `OPENAI_API_KEY` | Sim | Chave da OpenAI, usada pelo agente e pelo OCR | — |
| `JWT_SECRET` | Sim (em produção) | Segredo para assinar os tokens de login | valor de desenvolvimento |
| `DATABASE_URL` | Não | URL do banco | `sqlite:///./dockseal.db` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Não | Validade do token | `60` |
| `CORS_ORIGINS` | Não | Origens do front-end liberadas (lista JSON) | `["http://localhost:5173","http://localhost:3000"]` |
| `OPENAI_CHAT_MODEL` | Não | Modelo usado pelo agente | `gpt-4.1-mini` |
| `OPENAI_OCR_MODEL` | Não | Modelo usado no OCR | `gpt-4.1` |

Para gerar um `JWT_SECRET`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

> **PostgreSQL:** rode `uv add "psycopg[binary]"` e defina
> `DATABASE_URL=postgresql+psycopg://usuario:senha@localhost:5432/dockseal`.

**3. Instalar as dependências:**

```bash
uv sync
```

**4. Criar os usuários.** O sistema não tem cadastro livre: o acesso é liberado manualmente, como prevê o TCC. Para criar um usuário, use o terminal:

```bash
uv run python -m app.cli create-user "<nome>" <email> <senha> <PERFIL>
```

Exemplos:

```bash
uv run python -m app.cli create-user "Operador Teste" operador@dockseal.com senha123 OPERADOR
uv run python -m app.cli create-user "Gestor Teste" gestor@dockseal.com senha123 GESTOR
```

Os perfis válidos são `OPERADOR`, `GESTOR` e `ADMIN`.

## Rodando a aplicação

Em modo desenvolvimento (com recarga automática):

```bash
uv run fastapi dev main.py
```

Em modo produção:

```bash
uv run fastapi run main.py
```

A API fica em **http://localhost:8000**. Na primeira execução, as tabelas do banco e os perfis e permissões padrão são criados automaticamente.

Para verificar se a API está no ar:

```bash
curl localhost:8000/health
# {"status":"ok"}
```

## Perfis e permissões

| Permissão | OPERADOR | GESTOR | ADMIN |
|---|:-:|:-:|:-:|
| Registrar embarques e associar contêineres (`shipment:write`) | ✅ | | ✅ |
| Consultar embarques (`shipment:read`) | ✅ | ✅ | ✅ |
| Enviar documentos (`document:upload`) | ✅ | | ✅ |
| Executar análise com IA (`analysis:run`) | ✅ | ✅ | ✅ |
| Consultar alertas (`alert:read`) | ✅ | ✅ | ✅ |
| Resolver/fechar alertas (`alert:manage`) | | ✅ | ✅ |
| Consultar histórico/auditoria (`history:read`) | | ✅ | ✅ |

## Usando a API

### Pelo navegador (Swagger)

A forma mais fácil de testar:

1. Abra **http://localhost:8000/docs**.
2. Clique em **Authorize** (cadeado no canto superior direito).
3. Preencha `username` com o **e-mail** e `password` com a senha, e clique em **Authorize**.
4. Abra qualquer rota, clique em **Try it out**, preencha os campos e clique em **Execute**.

Os exemplos abaixo usam `curl` no terminal.

### 1. Login

`POST /auth/login`. O corpo é um **formulário** (`application/x-www-form-urlencoded`), não JSON. O campo `username` recebe o e-mail.

```bash
curl -X POST localhost:8000/auth/login \
  -d "username=operador@dockseal.com&password=senha123"
```

Resposta:

```json
{ "access_token": "eyJhbGciOi...", "token_type": "bearer" }
```

**Todas as outras rotas** (menos `/health`) exigem o cabeçalho:

```
Authorization: Bearer <access_token>
```

Para guardar o token numa variável:

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/login \
  -d "username=operador@dockseal.com&password=senha123" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
```

Para ver o usuário logado:

```bash
curl localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"
```

### 2. Análise de documentos (`POST /analysis`)

Esta é a funcionalidade principal. Você envia os arquivos e recebe a análise na hora, sem precisar cadastrar um embarque.

- **Formato:** `multipart/form-data`
- **Campo:** `files`, repetido uma vez para cada arquivo
- **Quantidade:** de 1 a 10 arquivos. Com 1 arquivo, o agente confere se ele é coerente por dentro (totais, datas, campos em branco, dígito do contêiner).
- **Formatos aceitos:** PDF, DOCX, TXT, CSV, MD, XML, JSON, PNG, JPG, JPEG e WEBP
- **Tamanho máximo:** 20 MB por arquivo

```bash
curl -X POST localhost:8000/analysis \
  -H "Authorization: Bearer $TOKEN" \
  -F files=@bill_of_lading.pdf \
  -F files=@nota_fiscal.pdf \
  -F files=@manifesto.docx
```

Como cada arquivo é lido:

| Arquivo | Leitura |
|---|---|
| DOCX, TXT, CSV, MD, XML, JSON | Localmente, sem IA |
| PDF com texto | Localmente, sem IA |
| PDF escaneado (só imagem) | OCR |
| PDF de formulário preenchido digitalmente (valores em anotações ou campos) | OCR, porque os valores ficam fora da camada de texto do PDF |
| PNG, JPG, WEBP | OCR |

No OCR, cada página é renderizada a 300 dpi e dividida em faixas horizontais antes de ir para o modelo de visão. Isso aumenta a resolução efetiva e reduz os erros em texto pequeno ou manuscrito. Leituras duvidosas são marcadas com `[?]` e trechos ilegíveis com `[ilegível]`; o agente não confirma divergências com base nesses valores e pede conferência humana.

> **Limitação:** letra manuscrita ainda pode ser lida errada. Confira os documentos escritos à mão.

O formato da resposta está descrito em [Formato da resposta da análise](#formato-da-resposta-da-análise).

### 3. Fluxo completo com embarque

Este é o fluxo descrito no TCC: registrar embarque → associar contêiner → enviar documentos → validar → consultar alertas.

**3.1 Registrar o embarque.** `POST /shipments`, com corpo **JSON**:

```bash
curl -X POST localhost:8000/shipments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "origin": "Santos",
    "destination": "Roterdã",
    "dispatched_at": "2026-10-03T10:00:00Z",
    "expected_return": "2026-11-03T10:00:00Z",
    "container": {
      "container_number": "MSCU 123456-7",
      "iso_code": "22G1",
      "type": "Dry 20'",
      "owner": "MSC"
    }
  }'
```

| Campo | Obrigatório | Observação |
|---|:-:|---|
| `origin`, `destination` | Sim | |
| `dispatched_at`, `expected_return` | Não | ISO 8601. O retorno não pode ser anterior ao despacho |
| `container` | Não | Pode ser associado depois. O número é normalizado (`MSCU 123456-7` → `MSCU1234567`) |

Guarde o `id` da resposta. Nos exemplos abaixo ele aparece como `ID_DO_EMBARQUE`.

**3.2 Associar ou trocar o contêiner (opcional).** `PUT /shipments/{id}/container`:

```bash
curl -X PUT localhost:8000/shipments/ID_DO_EMBARQUE/container \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"container_number": "MSCU1234567"}'
```

**3.3 Enviar os documentos do embarque.** `POST /shipments/{id}/documents`, em `multipart/form-data`:

- `files`: um ou mais arquivos
- `types` (opcional): o tipo de cada arquivo, **na mesma ordem** dos arquivos. Os valores possíveis são `BILL_OF_LADING`, `MANIFESTO_CARGA`, `NOTA_FISCAL`, `ORDEM_CARREGAMENTO` e `OUTRO`.

```bash
curl -X POST localhost:8000/shipments/ID_DO_EMBARQUE/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F files=@bl.pdf          -F types=BILL_OF_LADING \
  -F files=@manifesto.pdf   -F types=MANIFESTO_CARGA \
  -F files=@nf.pdf          -F types=NOTA_FISCAL
```

O texto de cada arquivo é extraído na hora e guardado. O arquivo original é salvo em `uploads/<id_do_embarque>/`.

**3.4 Validar o embarque.** `POST /shipments/{id}/validate`:

```bash
curl -X POST localhost:8000/shipments/ID_DO_EMBARQUE/validate \
  -H "Authorization: Bearer $TOKEN"
```

O que esta chamada faz:
- roda o agente sobre **todos** os documentos do embarque;
- salva o resultado como uma validação;
- cria um **alerta** para cada divergência com severidade `MEDIA`, `ALTA` ou `CRITICA`;
- muda o status do embarque para `VALIDATED` (sem divergências) ou `PENDING_REVIEW` (com divergências);
- registra o evento na trilha de auditoria.

**3.5 Consultar o embarque e as validações anteriores:**

```bash
curl localhost:8000/shipments -H "Authorization: Bearer $TOKEN"                                 # listar
curl localhost:8000/shipments/ID_DO_EMBARQUE -H "Authorization: Bearer $TOKEN"                  # detalhar
curl localhost:8000/shipments/ID_DO_EMBARQUE/validations -H "Authorization: Bearer $TOKEN"      # validações
```

### 4. Alertas e histórico

Use o login de um **GESTOR** para ter acesso a tudo.

**Listar alertas.** Eles vêm ordenados por criticidade e depois por data. Todos os filtros são opcionais:

```bash
curl "localhost:8000/alerts?status=OPEN&severity=CRITICA&shipment_id=ID_DO_EMBARQUE" \
  -H "Authorization: Bearer $TOKEN_GESTOR"
```

**Resolver ou fechar um alerta.** O `status` pode ser `OPEN`, `RESOLVED` ou `CLOSED`:

```bash
curl -X PATCH localhost:8000/alerts/ID_DO_ALERTA \
  -H "Authorization: Bearer $TOKEN_GESTOR" \
  -H "Content-Type: application/json" \
  -d '{"status": "RESOLVED"}'
```

**Histórico operacional (trilha de auditoria).** Registra logins, cadastros, uploads, análises e alertas:

```bash
curl "localhost:8000/events?shipment_id=ID_DO_EMBARQUE&limit=100" \
  -H "Authorization: Bearer $TOKEN_GESTOR"
```

## Referência de endpoints

| Método | Rota | Corpo | Permissão | Descrição |
|---|---|---|---|---|
| GET | `/health` | — | pública | Verifica se a API está no ar |
| POST | `/auth/login` | form: `username`, `password` | pública | Login, retorna o JWT |
| GET | `/auth/me` | — | autenticado | Dados do usuário logado |
| POST | `/analysis` | multipart: `files[]` | `analysis:run` | Analisa documentos avulsos |
| POST | `/shipments` | JSON | `shipment:write` | Registra embarque |
| GET | `/shipments` | query: `limit`, `offset` | `shipment:read` | Lista embarques |
| GET | `/shipments/{id}` | — | `shipment:read` | Detalha embarque com documentos |
| PUT | `/shipments/{id}/container` | JSON | `shipment:write` | Associa contêiner |
| POST | `/shipments/{id}/documents` | multipart: `files[]`, `types[]` | `document:upload` | Envia documentos do embarque |
| POST | `/shipments/{id}/validate` | — | `analysis:run` | Valida o embarque com o agente |
| GET | `/shipments/{id}/validations` | — | `shipment:read` | Histórico de validações |
| GET | `/alerts` | query: `status`, `severity`, `shipment_id` | `alert:read` | Lista alertas |
| PATCH | `/alerts/{id}` | JSON: `status` | `alert:manage` | Atualiza status do alerta |
| GET | `/events` | query: `shipment_id`, `limit` | `history:read` | Trilha de auditoria |

## Formato da resposta da análise

Este é o formato devolvido por `POST /analysis`. Em `POST /shipments/{id}/validate`, ele aparece dentro do campo `result`.

```json
{
  "status": "DIVERGENTE",
  "summary": "O peso bruto informado na Nota Fiscal (10 t) diverge do Bill of Lading e do Manifesto (2 t)...",
  "documents": [
    { "document": "bill_of_lading.pdf", "identified_type": "BILL_OF_LADING" },
    { "document": "nota_fiscal.pdf", "identified_type": "NOTA_FISCAL" }
  ],
  "divergences": [
    {
      "field": "peso bruto",
      "description": "O BL informa 2.000 kg e a Nota Fiscal informa 10 t.",
      "occurrences": [
        { "document": "bill_of_lading.pdf", "value": "2.000 kg", "excerpt": "Gross weight: 2.000 kg" },
        { "document": "nota_fiscal.pdf", "value": "10 t", "excerpt": "Peso bruto: 10 t" }
      ],
      "severity": "ALTA",
      "suggestion": "Corrigir o peso bruto da Nota Fiscal para 2.000 kg, conforme BL e Manifesto.",
      "document_to_fix": "nota_fiscal.pdf",
      "confidence": 0.93
    }
  ],
  "missing_fields": [
    {
      "field": "lacre",
      "present_in": ["bill_of_lading.pdf"],
      "missing_in": ["nota_fiscal.pdf"],
      "suggestion": "Incluir o número do lacre na Nota Fiscal."
    }
  ],
  "consistent_fields": ["número do contêiner", "porto de destino"],
  "confidence": 0.9
}
```

| Campo | Significado |
|---|---|
| `status` | `CONFORME` (sem divergências), `DIVERGENTE` (ao menos uma divergência) ou `INCONCLUSIVO` (texto ilegível ou insuficiente) |
| `summary` | Resumo da análise e da resolução sugerida |
| `documents` | Tipo que o agente identificou para cada arquivo |
| `divergences[].occurrences` | O valor e um trecho de cada documento, que comprovam a divergência |
| `divergences[].severity` | `CRITICA` (contêiner, lacre, BL), `ALTA` (peso, volumes, mercadoria), `MEDIA` (datas, navio, partes envolvidas), `BAIXA` (grafia ou formatação) |
| `divergences[].document_to_fix` | Documento que provavelmente precisa ser corrigido. É `null` quando é preciso conferência humana |
| `missing_fields` | Campos que aparecem em alguns documentos e faltam em outros |
| `consistent_fields` | Campos conferidos que estão coerentes |
| `confidence` | Confiança da análise, de 0 a 1 |

Regras que o agente segue:
- Ele converte unidades antes de comparar, então "2.000 kg" e "2 t" **não** contam como divergência.
- Quando precisa decidir qual valor está certo, prefere o que aparece na maioria dos documentos ou no documento de maior hierarquia: **Bill of Lading > Manifesto > Nota Fiscal > Ordem de Carregamento**.
- Ele não inventa valores. Quando não há base para decidir, indica que é necessária conferência humana.

As instruções do agente ficam em `app/agents/compliance_agent.py`.

## Erros comuns

| Código | Causa | O que fazer |
|---|---|---|
| `401` | Token ausente, inválido ou expirado (dura 60 min por padrão) | Fazer login de novo |
| `401` no login | E-mail ou senha incorretos | Conferir as credenciais |
| `403` | O perfil não tem a permissão (ex.: OPERADOR em `/events`) | Usar um usuário com o perfil adequado |
| `404` | Embarque ou alerta inexistente | Conferir o `id` |
| `413` | Arquivo maior que 20 MB | Reduzir o arquivo |
| `415` | Formato não suportado | Usar um dos [formatos aceitos](#2-análise-de-documentos-post-analysis) |
| `422` | Arquivo vazio, sem texto, mais de 10 arquivos, `types` com quantidade diferente de `files`, ou embarque sem documentos | Ver a mensagem em `detail` |
| `422` "OCR indisponível" | Imagem ou PDF escaneado enviado sem `OPENAI_API_KEY` | Configurar a chave no `.env` |
| `502` | Falha na chamada à OpenAI (o motivo vem em `detail`) | Conferir a chave, os créditos da conta e o nome do modelo |

## Testes

```bash
uv run pytest
```

Os testes usam um banco em memória e um **agente simulado**, então não precisam de chave da OpenAI e não consomem créditos. Eles cobrem login, permissões, a análise de múltiplos arquivos (TXT e DOCX) e o fluxo completo de embarque → documentos → validação → alerta → auditoria.

## Estrutura do projeto

```
backend_tcc/
├── main.py                         # Ponto de entrada (fastapi dev main.py)
├── app/
│   ├── main.py                     # Criação do FastAPI, rotas e criação do banco
│   ├── cli.py                      # Comando create-user
│   ├── agents/
│   │   └── compliance_agent.py     # Agente Agno: instruções, prompt e ComplianceAnalyzer
│   ├── api/
│   │   ├── deps.py                 # Autenticação, permissões e leitura de upload
│   │   ├── uploads.py              # Validação e extração dos arquivos enviados
│   │   └── routes/                 # auth, analysis, shipments, alerts
│   ├── core/
│   │   ├── config.py               # Configurações (.env)
│   │   ├── database.py             # Engine e sessão SQLAlchemy
│   │   └── security.py             # JWT e hash de senha
│   ├── models/                     # Entidades do diagrama de classes / ER
│   ├── schemas/
│   │   ├── analysis.py             # Formato da resposta do agente (AnalysisResult)
│   │   └── api.py                  # Schemas de entrada/saída da API
│   └── services/
│       ├── auth_service.py         # AuthenticationService, perfis e permissões
│       ├── extraction_service.py   # ExtractionService (PDF, DOCX, texto, OCR)
│       ├── validation_service.py   # ValidationService (análise, validação, alertas)
│       └── audit_service.py        # Registro de eventos (trilha de auditoria)
└── tests/
```

## Modelo de dados

As entidades seguem o diagrama de classes e o diagrama ER do TCC:

| Entidade | Descrição |
|---|---|
| `User`, `Role`, `Permission` | Usuários, perfis e permissões (RBAC) |
| `Shipment` | Embarque |
| `Container` | Contêiner associado ao embarque |
| `Document` | Documento do embarque (BL, Manifesto, NF, Ordem de Carregamento) |
| `Evidence` | Evidência operacional (fotos, comprovantes) |
| `Extraction` | Texto extraído de um documento ou evidência |
| `Validation` | Resultado da análise do agente |
| `Alert` | Alerta gerado por uma divergência |
| `ProcessEvent` | Evento da trilha de auditoria |
| `Job` | Tarefa de processamento assíncrono |

**Diferenças em relação ao diagrama:**
- `Validation` ganhou `shipment_id` e `result` (a análise completa em JSON).
- `Alert` ganhou `validation_id`.
- `Extraction` ganhou `document_id`, para guardar também o texto dos documentos, e não só o das evidências.

**Ainda não implementado:**
- **Processamento assíncrono:** a fila com Redis e os workers de OCR e IA ainda não existem. Hoje a análise roda direto na requisição, e a tabela `Job` existe mas ainda não é usada.
- **Rotas:** envio de evidências e dashboard de indicadores.
