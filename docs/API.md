# Guia da API Dockseal para o front-end

Tudo o que o front-end precisa para consumir a API: como autenticar, o que cada endpoint faz, o que enviar, o que volta e como tratar erros. Os exemplos de resposta foram copiados de chamadas reais.

> **Swagger interativo:** com a API rodando, abra **http://localhost:8000/docs**. Lá dá para testar cada rota (botão **Authorize** para logar) e ver os schemas. O JSON da especificação OpenAPI está em `http://localhost:8000/openapi.json`; dá para gerar um client TypeScript a partir dele (ex.: `npx openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts`).

## Sumário

1. [Configuração](#1-configuração)
2. [Convenções](#2-convenções)
3. [Autenticação](#3-autenticação)
4. [Perfis e permissões](#4-perfis-e-permissões)
5. [Endpoints](#5-endpoints)
   - [Autenticação](#51-autenticação)
   - [Análise de documentos](#52-análise-de-documentos)
   - [Embarques](#53-embarques)
   - [Alertas](#54-alertas)
   - [Histórico (auditoria)](#55-histórico-auditoria)
   - [Saúde](#56-saúde)
6. [Tipos TypeScript](#6-tipos-typescript)
7. [Erros](#7-erros)
8. [Fluxos de tela sugeridos](#8-fluxos-de-tela-sugeridos)
9. [Client pronto (fetch)](#9-client-pronto-fetch)

---

## 1. Configuração

| Item | Valor |
|---|---|
| URL base (desenvolvimento) | `http://localhost:8000` |
| Formato | JSON, exceto login (formulário) e uploads (`multipart/form-data`) |
| CORS liberado para | `http://localhost:5173` (Vite) e `http://localhost:3000` |

Se o front rodar em outra porta ou domínio, peça para o backend adicionar a origem em `CORS_ORIGINS` no `.env`:

```
CORS_ORIGINS=["http://localhost:5173","https://dockseal.exemplo.com"]
```

Sugestão de variável no front: `VITE_API_URL=http://localhost:8000`.

## 2. Convenções

- **IDs** são UUIDs em texto (`"b115cff4-9ec1-4fa2-bba1-f8584cab877f"`).
- **Datas** chegam sempre em ISO 8601 UTC com `Z` (`"2026-10-03T10:00:00Z"`). Para exibir, use `new Date(valor).toLocaleString("pt-BR")`. Ao enviar, mande ISO com `Z` (`date.toISOString()`).
- **Enums** chegam como texto em maiúsculas (`"PENDING_REVIEW"`, `"CRITICA"`). As tabelas de tradução para a tela estão em [Tipos TypeScript](#6-tipos-typescript).
- **Erros** sempre têm o campo `detail` (ver [Erros](#7-erros)).
- **Listas** retornam um array direto, sem envelope (`[{...}, {...}]`).
- **Rotas de IA são lentas:** `POST /analysis` e `POST /shipments/{id}/validate` levam de **10 a 40 segundos**. Mostre um loading e não use timeout menor que 90 s.

## 3. Autenticação

Fluxo:

1. O usuário faz login com e-mail e senha em `POST /auth/login` e recebe um `access_token` (JWT).
2. O front guarda o token (ex.: `localStorage`) e o envia em **todas** as outras requisições:
   ```
   Authorization: Bearer <access_token>
   ```
3. Logo após o login, chame `GET /auth/me` para pegar nome, perfil e **permissões**, e montar o menu.
4. O token expira em **60 minutos**. Qualquer resposta **401** significa token ausente, inválido ou expirado: apague o token e mande para a tela de login.
5. **Logout** é só apagar o token no front (não há rota de logout).

> Não existe cadastro pela API. Os usuários são criados pela equipe do backend. O botão "solicitar acesso" da tela de login pode abrir um e-mail ou formulário externo.

## 4. Perfis e permissões

`GET /auth/me` devolve `permissions`. **Use as permissões, não o nome do perfil**, para mostrar ou esconder telas e botões.

| Permissão | O que libera | OPERADOR | GESTOR | ADMIN |
|---|---|:-:|:-:|:-:|
| `shipment:read` | Ver embarques e validações | ✅ | ✅ | ✅ |
| `shipment:write` | Criar embarque, associar contêiner | ✅ | | ✅ |
| `document:upload` | Enviar documentos do embarque | ✅ | | ✅ |
| `analysis:run` | `POST /analysis` e validar embarque | ✅ | ✅ | ✅ |
| `alert:read` | Ver alertas | ✅ | ✅ | ✅ |
| `alert:manage` | Resolver/fechar alertas | | ✅ | ✅ |
| `history:read` | Ver histórico/auditoria | | ✅ | ✅ |

Se o usuário chamar uma rota sem permissão, a API responde **403**.

---

## 5. Endpoints

Resumo:

| Método | Rota | Para que serve | Permissão |
|---|---|---|---|
| POST | [`/auth/login`](#post-authlogin) | Login | pública |
| GET | [`/auth/me`](#get-authme) | Usuário logado e permissões | autenticado |
| POST | [`/analysis`](#post-analysis) | Analisar documentos avulsos com IA | `analysis:run` |
| POST | [`/shipments`](#post-shipments) | Criar embarque | `shipment:write` |
| GET | [`/shipments`](#get-shipments) | Listar embarques | `shipment:read` |
| GET | [`/shipments/{id}`](#get-shipmentsid) | Detalhe do embarque + documentos | `shipment:read` |
| PUT | [`/shipments/{id}/container`](#put-shipmentsidcontainer) | Associar/trocar contêiner | `shipment:write` |
| POST | [`/shipments/{id}/documents`](#post-shipmentsiddocuments) | Enviar documentos do embarque | `document:upload` |
| POST | [`/shipments/{id}/validate`](#post-shipmentsidvalidate) | Validar embarque com IA | `analysis:run` |
| GET | [`/shipments/{id}/validations`](#get-shipmentsidvalidations) | Histórico de validações | `shipment:read` |
| GET | [`/alerts`](#get-alerts) | Listar alertas | `alert:read` |
| PATCH | [`/alerts/{id}`](#patch-alertsid) | Resolver/fechar/reabrir alerta | `alert:manage` |
| GET | [`/events`](#get-events) | Histórico/auditoria | `history:read` |
| GET | [`/health`](#get-health) | API está no ar? | pública |

### 5.1 Autenticação

#### `POST /auth/login`

Faz login e devolve o token.

**Atenção:** o corpo é **formulário** (`application/x-www-form-urlencoded`), não JSON. O campo do e-mail se chama `username`.

| Campo | Tipo | Obrigatório |
|---|---|:-:|
| `username` | string (e-mail) | ✅ |
| `password` | string | ✅ |

```ts
const res = await fetch(`${API}/auth/login`, {
  method: "POST",
  body: new URLSearchParams({ username: email, password }),
});
```

**200:**
```json
{ "access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer" }
```

| Erro | Quando | Mensagem para o usuário |
|---|---|---|
| 401 | E-mail ou senha errados, ou usuário inativo | `detail`: "E-mail ou senha inválidos" |
| 422 | Campo faltando | "Preencha e-mail e senha" |

---

#### `GET /auth/me`

Dados do usuário logado. Chame logo após o login e ao recarregar a página.

**200:**
```json
{
  "id": "2c1663b1-7b0a-4a25-8e38-3f37c24a723d",
  "name": "Gestor",
  "email": "gestor@dockseal.com",
  "status": "ACTIVE",
  "role": { "name": "GESTOR" },
  "permissions": ["alert:manage", "alert:read", "analysis:run", "history:read", "shipment:read"]
}
```

| Erro | Quando |
|---|---|
| 401 | Token ausente, inválido ou expirado → ir para o login |

---

### 5.2 Análise de documentos

#### `POST /analysis`

**A funcionalidade principal.** O usuário envia de 1 a 10 documentos e a IA devolve as divergências entre eles, com sugestão de correção. Não precisa de embarque cadastrado e não salva os arquivos. A análise fica registrada na auditoria.

- **Corpo:** `multipart/form-data`, com **todos os arquivos no campo `files`** (repita o campo).
- **Formatos:** PDF, DOCX, TXT, CSV, MD, XML, JSON, PNG, JPG, JPEG, WEBP (sugestão para o `<input>`: `accept=".pdf,.docx,.txt,.csv,.md,.xml,.json,.png,.jpg,.jpeg,.webp"`).
- **Limites:** 20 MB por arquivo, 10 arquivos por envio.
- **Tempo:** de 10 a 40 segundos.
- **Com 1 arquivo**, a IA confere se o documento é coerente por dentro (totais, datas, campos em branco).

```ts
const form = new FormData();
for (const file of arquivos) form.append("files", file); // mesmo nome "files" para todos

const res = await fetch(`${API}/analysis`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}` }, // NÃO defina Content-Type: o navegador coloca o boundary
  body: form,
});
```

**200** (`AnalysisResult`, exemplo real):
```json
{
  "status": "DIVERGENTE",
  "summary": "O peso bruto na Nota Fiscal (10 t) diverge do Bill of Lading e do Manifesto (18 t)...",
  "documents": [
    { "document": "bill_of_lading.pdf", "identified_type": "BILL_OF_LADING" },
    { "document": "nota_fiscal.docx", "identified_type": "NOTA_FISCAL" },
    { "document": "manifesto.txt", "identified_type": "MANIFESTO_CARGA" }
  ],
  "divergences": [
    {
      "field": "número do contêiner",
      "description": "O número do contêiner no Manifesto de Carga (MSCU7654321) difere do Bill of Lading e da Nota Fiscal (MSCU1234567).",
      "occurrences": [
        { "document": "bill_of_lading.pdf", "value": "MSCU1234567", "excerpt": "Container: MSCU1234567" },
        { "document": "nota_fiscal.docx", "value": "MSCU1234567", "excerpt": "Contêiner MSCU1234567" },
        { "document": "manifesto.txt", "value": "MSCU7654321", "excerpt": "Contêiner: MSCU7654321" }
      ],
      "severity": "CRITICA",
      "suggestion": "Corrigir o número do contêiner no Manifesto de Carga para MSCU1234567.",
      "document_to_fix": "manifesto.txt",
      "confidence": 1.0
    }
  ],
  "missing_fields": [],
  "consistent_fields": ["número do BL", "exportador", "navio", "porto de destino"],
  "confidence": 0.95
}
```

O que cada campo significa e como mostrar na tela:

| Campo | Significado | Sugestão de UI |
|---|---|---|
| `status` | `CONFORME` (nada a corrigir), `DIVERGENTE` (há divergências) ou `INCONCLUSIVO` (documentos ilegíveis, insuficientes ou de operações diferentes) | Badge no topo: verde / vermelho / amarelo |
| `summary` | Resumo em português | Parágrafo abaixo do badge |
| `documents[]` | Tipo que a IA identificou para cada arquivo | Lista de arquivos com uma etiqueta do tipo |
| `divergences[]` | Uma entrada por campo que não bate | Cards ou tabela, ordenados por severidade |
| `divergences[].occurrences[]` | O valor que aparece em cada documento, com um trecho (`excerpt`) | Tabela "Documento × Valor", destacando o valor diferente |
| `divergences[].suggestion` | O que corrigir | Destaque no card |
| `divergences[].document_to_fix` | Documento que provavelmente deve ser corrigido; `null` quando a IA não sabe | "Corrigir em: manifesto.txt" ou "Requer conferência humana" |
| `divergences[].confidence` / `confidence` | Confiança de 0 a 1 | Mostrar como % (`Math.round(c * 100)`) |
| `missing_fields[]` | Campos presentes em alguns documentos e ausentes em outros | Seção "Campos ausentes" |
| `consistent_fields[]` | Campos conferidos que estão iguais | Chips verdes "Conferido" |

> Valores lidos de documentos manuscritos podem vir com `[?]` (leitura duvidosa) ou `[ilegível]`. Mostre-os como estão; a IA já reduz a confiança nesses casos.

| Erro | Quando |
|---|---|
| 413 | Arquivo maior que 20 MB |
| 415 | Formato não suportado |
| 422 | Nenhum arquivo, arquivo vazio ou sem texto, mais de 10 arquivos |
| 502 | Falha na IA (sem créditos, fora do ar...). `detail` traz o motivo; mostre "Não foi possível analisar agora, tente novamente" |

---

### 5.3 Embarques

O fluxo completo descrito no TCC: **criar embarque → (associar contêiner) → enviar documentos → validar → ver alertas**.

#### `POST /shipments`

Cria um embarque. Corpo **JSON**.

| Campo | Tipo | Obrigatório | Observação |
|---|---|:-:|---|
| `origin` | string | ✅ | |
| `destination` | string | ✅ | |
| `dispatched_at` | string ISO | | Data de despacho |
| `expected_return` | string ISO | | Não pode ser anterior a `dispatched_at` |
| `container` | objeto | | Pode ser associado depois |
| `container.container_number` | string (4–20) | ✅ se enviar `container` | Espaços e hífens são removidos: `"MSCU 123456-7"` vira `"MSCU1234567"` |
| `container.iso_code` | string | | Ex.: `"22G1"` |
| `container.type` | string | | Ex.: `"Dry 20'"` |
| `container.owner` | string | | Ex.: `"MSC"` |

```json
{
  "origin": "Santos",
  "destination": "Roterdã",
  "dispatched_at": "2026-10-03T10:00:00Z",
  "expected_return": "2026-11-03T10:00:00Z",
  "container": { "container_number": "MSCU 123456-7", "iso_code": "22G1", "owner": "MSC" }
}
```

**201** → um `Shipment` (mesmo formato do [`GET /shipments/{id}`](#get-shipmentsid), mas sem `documents`).

| Erro | Quando |
|---|---|
| 403 | Usuário sem `shipment:write` (ex.: GESTOR) |
| 422 | Campo obrigatório faltando ou vazio, ou retorno anterior ao despacho |

---

#### `GET /shipments`

Lista embarques, os mais recentes primeiro.

| Query | Padrão | Descrição |
|---|---|---|
| `limit` | 50 | Quantos itens trazer |
| `offset` | 0 | Quantos pular (paginação: página `p` → `offset = (p - 1) * limit`) |

A resposta não traz o total de itens. Para saber se há próxima página, verifique se vieram `limit` itens.

**200** → `Shipment[]` (sem `documents`).

---

#### `GET /shipments/{id}`

Detalhe do embarque, **com a lista de documentos**.

**200** (exemplo real):
```json
{
  "id": "b115cff4-9ec1-4fa2-bba1-f8584cab877f",
  "origin": "Santos",
  "destination": "Rotterdam",
  "dispatched_at": "2026-10-03T10:00:00Z",
  "expected_return": "2026-11-03T10:00:00Z",
  "returned_at": null,
  "status": "PENDING_REVIEW",
  "container": {
    "id": "f83bdc18-8e51-4e71-84a5-8b0d842f9511",
    "container_number": "MSCU1234567",
    "iso_code": "22G1",
    "type": null,
    "owner": "MSC",
    "status": "AVAILABLE"
  },
  "created_at": "2026-10-03T22:49:36.753384Z",
  "documents": [
    { "id": "ac965a6e-...", "type": "BILL_OF_LADING", "filename": "bill_of_lading.pdf", "status": "EXTRACTED", "created_at": "2026-10-03T22:49:36.996554Z" },
    { "id": "c1f098eb-...", "type": "NOTA_FISCAL", "filename": "nota_fiscal.docx", "status": "EXTRACTED", "created_at": "2026-10-03T22:49:36.996586Z" }
  ]
}
```

Status do embarque:

| `status` | Significado | Cor sugerida |
|---|---|---|
| `REGISTERED` | Cadastrado, ainda não validado | cinza |
| `VALIDATED` | Validado, sem divergências | verde |
| `PENDING_REVIEW` | Validado com divergências ou resultado inconclusivo | vermelho/amarelo |

| Erro | Quando |
|---|---|
| 404 | Embarque não existe |

---

#### `PUT /shipments/{id}/container`

Associa um contêiner ao embarque ou troca o atual. Se o número já existir, reaproveita o contêiner existente. Corpo **JSON**, igual ao objeto `container` do `POST /shipments`:

```json
{ "container_number": "MSCU1234567", "iso_code": "22G1", "type": "Dry 20'", "owner": "MSC" }
```

**200** → o `Shipment` atualizado.

---

#### `POST /shipments/{id}/documents`

Envia um ou mais documentos para o embarque. O texto é extraído na hora e guardado para a validação.

- **Corpo:** `multipart/form-data`.
- `files`: um ou mais arquivos (mesmos formatos e limites do `/analysis`).
- `types` (opcional): o tipo de cada arquivo, **na mesma ordem e na mesma quantidade** dos arquivos. Sem `types`, todos ficam como `OUTRO`.

Valores de `types`:

| Valor | Mostrar como |
|---|---|
| `BILL_OF_LADING` | Bill of Lading |
| `MANIFESTO_CARGA` | Manifesto de Carga |
| `NOTA_FISCAL` | Nota Fiscal |
| `ORDEM_CARREGAMENTO` | Ordem de Carregamento |
| `OUTRO` | Outro |

```ts
const form = new FormData();
form.append("files", arquivoBL);        form.append("types", "BILL_OF_LADING");
form.append("files", arquivoManifesto); form.append("types", "MANIFESTO_CARGA");

await fetch(`${API}/shipments/${id}/documents`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}` },
  body: form,
});
```

**201** → `Document[]` com os documentos criados.

| Erro | Quando |
|---|---|
| 404 | Embarque não existe |
| 413 / 415 | Arquivo grande demais / formato não suportado |
| 422 | Arquivo vazio ou sem texto, ou `types` com quantidade diferente de `files` |

> Ainda não há rota para baixar ou excluir documentos.

---

#### `POST /shipments/{id}/validate`

Roda a IA sobre **todos os documentos do embarque**. Sem corpo. A validação:

- salva o resultado (aparece em `/validations`);
- cria um **alerta** para cada divergência de severidade `MEDIA`, `ALTA` ou `CRITICA`;
- muda o `status` do embarque para `VALIDATED` ou `PENDING_REVIEW`.

Leva de 10 a 40 segundos.

**200** → `Validation`:
```json
{
  "id": "5b653c82-7b92-4700-b1e4-1ea237c52aa9",
  "status": "DIVERGENTE",
  "details": "Resumo da análise...",
  "confidence_score": 0.95,
  "shipment_id": "b115cff4-9ec1-4fa2-bba1-f8584cab877f",
  "result": { "...": "mesmo formato do AnalysisResult do POST /analysis" },
  "created_at": "2026-10-03T23:02:24.556974Z"
}
```

Depois da validação, recarregue o embarque (status novo) e os alertas.

| Erro | Quando |
|---|---|
| 404 | Embarque não existe |
| 422 | Embarque sem documentos: "O embarque não possui documentos com texto extraído para analisar." |
| 502 | Falha na IA |

---

#### `GET /shipments/{id}/validations`

Todas as validações do embarque, as mais recentes primeiro. A primeira do array é a atual.

**200** → `Validation[]`.

---

### 5.4 Alertas

#### `GET /alerts`

Lista alertas, ordenados por **criticidade** (CRITICA → ALTA → MEDIA → BAIXA) e depois pelos **mais recentes**.

| Query | Valores | Descrição |
|---|---|---|
| `status` | `OPEN`, `RESOLVED`, `CLOSED` | Filtra por status |
| `severity` | `BAIXA`, `MEDIA`, `ALTA`, `CRITICA` | Filtra por severidade |
| `shipment_id` | UUID | Alertas de um embarque |

Exemplo: `GET /alerts?status=OPEN&severity=CRITICA`

**200** (exemplo real):
```json
[
  {
    "id": "e7e7d3c6-3faf-46c0-95b3-05adc31cc5fa",
    "severity": "CRITICA",
    "description": "lacre: O lacre no Manifesto de Carga é SL-884599, divergente do Bill of Lading e Nota Fiscal que indicam SL-884512. Sugestão: Corrigir o lacre no Manifesto de Carga para SL-884512, conforme Bill of Lading e Nota Fiscal.",
    "status": "OPEN",
    "shipment_id": "b115cff4-9ec1-4fa2-bba1-f8584cab877f",
    "validation_id": "5b653c82-7b92-4700-b1e4-1ea237c52aa9",
    "created_at": "2026-10-03T23:02:24.560184Z"
  }
]
```

`description` segue o formato `"<campo>: <descrição> Sugestão: <sugestão>"`. Para o painel de detalhe do alerta, os dados completos (valores em cada documento) estão na validação: busque `GET /shipments/{shipment_id}/validations` e encontre a validação de `id === validation_id`.

| `severity` | Mostrar como | Cor sugerida |
|---|---|---|
| `CRITICA` | Crítica | vermelho |
| `ALTA` | Alta | laranja |
| `MEDIA` | Média | amarelo |
| `BAIXA` | Baixa | cinza/azul |

| `status` | Mostrar como |
|---|---|
| `OPEN` | Aberto |
| `RESOLVED` | Resolvido |
| `CLOSED` | Fechado |

---

#### `PATCH /alerts/{id}`

Muda o status do alerta. Só para quem tem `alert:manage` (GESTOR/ADMIN). Corpo **JSON**:

```json
{ "status": "RESOLVED" }
```

Botões sugeridos: "Marcar como resolvido" → `RESOLVED`, "Falso positivo" → `CLOSED`, "Reabrir" → `OPEN`.

**200** → o `Alert` atualizado.

| Erro | Quando |
|---|---|
| 403 | Usuário sem `alert:manage` |
| 404 | Alerta não existe |
| 422 | `status` com valor inválido |

---

### 5.5 Histórico (auditoria)

#### `GET /events`

Trilha de auditoria, a mais recente primeiro. Só para quem tem `history:read`.

| Query | Padrão | Descrição |
|---|---|---|
| `shipment_id` | — | Eventos de um embarque |
| `limit` | 100 | Quantos trazer |

**200** (exemplo real):
```json
[
  {
    "id": "e4520d07-5b21-4cca-b8e0-45abdb8d6885",
    "step": "LOGIN",
    "status": "SUCCESS",
    "observation": null,
    "user_id": "2c1663b1-7b0a-4a25-8e38-3f37c24a723d",
    "shipment_id": null,
    "created_at": "2026-10-03T23:57:39.664076Z"
  }
]
```

| `step` | Mostrar como |
|---|---|
| `LOGIN` | Login |
| `SHIPMENT_CREATED` | Embarque registrado |
| `CONTAINER_ASSOCIATED` | Contêiner associado |
| `DOCUMENTS_UPLOADED` | Documentos enviados |
| `VALIDATION` | Validação do embarque |
| `ANALYSIS` | Análise de documentos avulsos |
| `ALERT_OPEN` / `ALERT_RESOLVED` / `ALERT_CLOSED` | Alerta reaberto / resolvido / fechado |

`status` é `SUCCESS`, `FAILURE` ou, nas análises, o resultado (`CONFORME`, `DIVERGENTE`, `INCONCLUSIVO`).

> O evento traz só o `user_id`, não o nome do usuário.

---

### 5.6 Saúde

#### `GET /health`

Não precisa de token. **200:** `{"status": "ok"}`.

---

## 6. Tipos TypeScript

Copie para `src/api/types.ts`:

```ts
// ---------- Enums ----------
export type RoleName = "OPERADOR" | "GESTOR" | "ADMIN";
export type Permission =
  | "shipment:read" | "shipment:write" | "document:upload" | "analysis:run"
  | "alert:read" | "alert:manage" | "history:read";
export type ShipmentStatus = "REGISTERED" | "VALIDATED" | "PENDING_REVIEW";
export type DocumentType = "BILL_OF_LADING" | "MANIFESTO_CARGA" | "NOTA_FISCAL" | "ORDEM_CARREGAMENTO" | "OUTRO";
export type AnalysisStatus = "CONFORME" | "DIVERGENTE" | "INCONCLUSIVO";
export type Severity = "BAIXA" | "MEDIA" | "ALTA" | "CRITICA";
export type AlertStatus = "OPEN" | "RESOLVED" | "CLOSED";

// ---------- Autenticação ----------
export interface Token { access_token: string; token_type: "bearer" }

export interface User {
  id: string;
  name: string;
  email: string;
  status: string;
  role: { name: RoleName };
  permissions: Permission[];
}

// ---------- Análise ----------
export interface FieldOccurrence { document: string; value: string; excerpt: string | null }

export interface Divergence {
  field: string;
  description: string;
  occurrences: FieldOccurrence[];
  severity: Severity;
  suggestion: string;
  document_to_fix: string | null;
  confidence: number; // 0 a 1
}

export interface MissingField { field: string; present_in: string[]; missing_in: string[]; suggestion: string }

export interface AnalysisResult {
  status: AnalysisStatus;
  summary: string;
  documents: { document: string; identified_type: DocumentType }[];
  divergences: Divergence[];
  missing_fields: MissingField[];
  consistent_fields: string[];
  confidence: number; // 0 a 1
}

// ---------- Embarques ----------
export interface ContainerInput { container_number: string; iso_code?: string; type?: string; owner?: string }

export interface Container {
  id: string;
  container_number: string;
  iso_code: string | null;
  type: string | null;
  owner: string | null;
  status: string;
}

export interface ShipmentInput {
  origin: string;
  destination: string;
  dispatched_at?: string;   // ISO UTC
  expected_return?: string; // ISO UTC
  container?: ContainerInput;
}

export interface Shipment {
  id: string;
  origin: string;
  destination: string;
  dispatched_at: string | null;
  expected_return: string | null;
  returned_at: string | null;
  status: ShipmentStatus;
  container: Container | null;
  created_at: string;
}

export interface ShipmentDocument {
  id: string;
  type: DocumentType;
  filename: string;
  status: string;
  created_at: string;
}

export interface ShipmentDetail extends Shipment { documents: ShipmentDocument[] }

export interface Validation {
  id: string;
  status: AnalysisStatus;
  details: string;
  confidence_score: number | null;
  shipment_id: string | null;
  result: AnalysisResult;
  created_at: string;
}

// ---------- Alertas e histórico ----------
export interface Alert {
  id: string;
  severity: Severity;
  description: string;
  status: AlertStatus;
  shipment_id: string | null;
  validation_id: string | null;
  created_at: string;
}

export interface ProcessEvent {
  id: string;
  step: string;
  status: string;
  observation: string | null;
  user_id: string | null;
  shipment_id: string | null;
  created_at: string;
}

// ---------- Erros ----------
export interface ValidationErrorItem { type: string; loc: (string | number)[]; msg: string; input?: unknown }
export interface ApiErrorBody { detail: string | ValidationErrorItem[] }

// ---------- Traduções para a tela ----------
export const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  BILL_OF_LADING: "Bill of Lading",
  MANIFESTO_CARGA: "Manifesto de Carga",
  NOTA_FISCAL: "Nota Fiscal",
  ORDEM_CARREGAMENTO: "Ordem de Carregamento",
  OUTRO: "Outro",
};
export const SHIPMENT_STATUS_LABEL: Record<ShipmentStatus, string> = {
  REGISTERED: "Cadastrado",
  VALIDATED: "Validado",
  PENDING_REVIEW: "Pendente de revisão",
};
export const ANALYSIS_STATUS_LABEL: Record<AnalysisStatus, string> = {
  CONFORME: "Conforme",
  DIVERGENTE: "Divergente",
  INCONCLUSIVO: "Inconclusivo",
};
export const SEVERITY_LABEL: Record<Severity, string> = {
  BAIXA: "Baixa", MEDIA: "Média", ALTA: "Alta", CRITICA: "Crítica",
};
export const ALERT_STATUS_LABEL: Record<AlertStatus, string> = {
  OPEN: "Aberto", RESOLVED: "Resolvido", CLOSED: "Fechado",
};
```

## 7. Erros

Todo erro tem o campo `detail`, em **dois formatos**:

**a) Texto** (erros de regra de negócio: 401, 403, 404, 413, 415, alguns 422, 502). Pode mostrar direto para o usuário:
```json
{ "detail": "Embarque não encontrado" }
```

**b) Lista** (422 de validação de campos, quando o corpo veio com campo faltando ou no formato errado):
```json
{
  "detail": [
    { "type": "string_too_short", "loc": ["body", "origin"], "msg": "String should have at least 1 character", "input": "" },
    { "type": "missing", "loc": ["body", "destination"], "msg": "Field required", "input": { "origin": "" } }
  ]
}
```
O último item de `loc` é o nome do campo, útil para marcar o input com erro. As mensagens (`msg`) vêm em inglês, então é melhor exibir uma mensagem própria por campo.

| Código | Significado | O que o front deve fazer |
|---|---|---|
| 401 | Token ausente, inválido ou expirado | Apagar o token e ir para o login |
| 403 | Sem permissão | Mostrar "Você não tem permissão" (e esconder o botão, ver [permissões](#4-perfis-e-permissões)) |
| 404 | Recurso não existe | Mostrar "não encontrado" e voltar para a lista |
| 413 | Arquivo maior que 20 MB | Validar o tamanho antes de enviar |
| 415 | Formato não suportado | Usar `accept` no input de arquivo |
| 422 | Dados inválidos | Mostrar a mensagem (texto) ou marcar os campos (lista) |
| 502 | A IA falhou | "Não foi possível analisar agora, tente novamente em instantes" |

## 8. Fluxos de tela sugeridos

Telas do protótipo do TCC (IHM) e as chamadas de cada uma:

| Tela | Chamadas |
|---|---|
| **Login** | `POST /auth/login` → guardar token → `GET /auth/me` |
| **Visão geral (dashboard)** | `GET /shipments` (contar por `status`) + `GET /alerts?status=OPEN` (contar por `severity`). Não há rota de indicadores pronta; os números são calculados no front |
| **Análise rápida** | `POST /analysis` com os arquivos → renderizar o `AnalysisResult` |
| **Histórico de embarques** | `GET /shipments?limit=20&offset=...` |
| **Novo embarque** | `POST /shipments` → `POST /shipments/{id}/documents` → `POST /shipments/{id}/validate` → `GET /shipments/{id}` |
| **Detalhe do embarque** | `GET /shipments/{id}` + `GET /shipments/{id}/validations` (resultado da IA = primeira validação, campo `result`) + `GET /alerts?shipment_id={id}` |
| **Central de alertas** | `GET /alerts?status=&severity=` → no detalhe, buscar a validação pelo `validation_id` → `PATCH /alerts/{id}` nos botões |
| **Auditoria** | `GET /events?shipment_id=` (somente com `history:read`) |

O que ainda não existe na API (não tente consumir): envio de evidências (fotos), download de documentos, indicadores prontos para o dashboard, exportação de relatórios, recuperação de senha e cadastro de usuários.

## 9. Client pronto (fetch)

Um client mínimo que já trata token, erros e upload. Copie para `src/api/client.ts` e ajuste.

```ts
import type {
  AlertStatus, Alert, AnalysisResult, ApiErrorBody, DocumentType, ProcessEvent,
  Severity, Shipment, ShipmentDetail, ShipmentDocument, ShipmentInput, ContainerInput,
  Token, User, Validation,
} from "./types";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "dockseal_token";

export class ApiError extends Error {
  constructor(public status: number, public body: ApiErrorBody | null) {
    super(typeof body?.detail === "string" ? body.detail : `Erro ${status}`);
  }
}

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const logout = () => localStorage.removeItem(TOKEN_KEY);

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");

  const res = await fetch(`${API}${path}`, { ...init, headers });
  if (res.status === 401) {
    logout();
    window.location.href = "/login"; // ajuste para o seu roteador
  }
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  return res.json() as Promise<T>;
}

const json = (body: unknown) => JSON.stringify(body);
const query = (params: Record<string, string | number | undefined>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
};

export const api = {
  // Autenticação
  async login(email: string, password: string): Promise<User> {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      body: new URLSearchParams({ username: email, password }),
    });
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    const { access_token } = (await res.json()) as Token;
    localStorage.setItem(TOKEN_KEY, access_token);
    return api.me();
  },
  me: () => request<User>("/auth/me"),

  // Análise avulsa (10 a 40 s)
  analyze(files: File[]) {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<AnalysisResult>("/analysis", { method: "POST", body: form });
  },

  // Embarques
  listShipments: (limit = 50, offset = 0) => request<Shipment[]>(`/shipments${query({ limit, offset })}`),
  getShipment: (id: string) => request<ShipmentDetail>(`/shipments/${id}`),
  createShipment: (data: ShipmentInput) => request<Shipment>("/shipments", { method: "POST", body: json(data) }),
  setContainer: (id: string, data: ContainerInput) =>
    request<Shipment>(`/shipments/${id}/container`, { method: "PUT", body: json(data) }),
  uploadDocuments(id: string, docs: { file: File; type: DocumentType }[]) {
    const form = new FormData();
    docs.forEach(({ file, type }) => {
      form.append("files", file);
      form.append("types", type);
    });
    return request<ShipmentDocument[]>(`/shipments/${id}/documents`, { method: "POST", body: form });
  },
  validateShipment: (id: string) => request<Validation>(`/shipments/${id}/validate`, { method: "POST" }),
  listValidations: (id: string) => request<Validation[]>(`/shipments/${id}/validations`),

  // Alertas
  listAlerts: (f: { status?: AlertStatus; severity?: Severity; shipment_id?: string } = {}) =>
    request<Alert[]>(`/alerts${query(f)}`),
  setAlertStatus: (id: string, status: AlertStatus) =>
    request<Alert>(`/alerts/${id}`, { method: "PATCH", body: json({ status }) }),

  // Histórico
  listEvents: (f: { shipment_id?: string; limit?: number } = {}) => request<ProcessEvent[]>(`/events${query(f)}`),
};

export const can = (user: User | null, permission: User["permissions"][number]) =>
  !!user?.permissions.includes(permission);
```

Exemplo de uso:

```ts
try {
  const user = await api.login(email, senha);
  if (can(user, "history:read")) mostrarMenuAuditoria();

  const resultado = await api.analyze(arquivosSelecionados);
  console.log(resultado.status, resultado.divergences);
} catch (e) {
  if (e instanceof ApiError) toast.error(e.message); // detail já em português nos erros de negócio
}
```

---

**Usuários de teste** (ambiente local): peça ao time de backend. Eles são criados com
`uv run python -m app.cli create-user "<nome>" <email> <senha> <OPERADOR|GESTOR|ADMIN>`.
