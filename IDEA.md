# IDEA & Evolução do Projeto

## Visão Original

> *Requisitos iniciais levantados para o projeto:*
> - Extrair informações dos payloads JSON de banco (`br.com.cvale.sap.extratoaves.v1`) e organizar em uma base estruturada para consulta no **DBeaver** e exportação em `.csv` / `.xlsx`.
> - Decodificar os binários **PDF Base64** (`PDF64`) e conferir se as informações estão corretas por meio de **testes unitários** sobre a integração **MTech → AgroCenter → Produtor**.
> - Criar **skills** para apoiar a rotina contínua de conferência quando novos arquivos forem adicionados em `data/raw/`.
> - Gerar **relatório executivo** e pacote de **issues** para demonstrar aos stakeholders o status de homologação da solução.

---

## Como a Ideia Evoluiu

A solução evoluiu de um simples extrator para uma **plataforma completa de QA e Auditoria de Interoperabilidade**:

1. **Rigor LGPD no Roteamento ao Produtor:** `Cod_Cliente` (JSON) e `BP` (PDF) são validados de forma obrigatória e estrita em todas as páginas, bloqueando qualquer risco de entrega indevida de extrato a outro produtor. Na regra de negócio **Granja × Aviário**, o proprietário do aviário (`cod_BP_Proprietario`) e o responsável pela granja (`cod_BP_Responsavel`) podem ser BPs distintos (mapeados em `data/cod_bp/cod_BP_integracao.md` / tabela `ref_aviario_bp`), exigindo que JSON e PDF utilizem exatamente o mesmo papel/coluna.
2. **Idempotência & Determinismo Binário (Blockchain-ready):** além de comparar o hash do arquivo e do texto canônico, o pipeline audita a unicidade de `BrimGrowSettlementsIRN` e do hash SHA-256 binário do PDF por lote composto (`aviario-lote`).
3. **Resiliência a Novos Payloads:** suporte a subpastas em `data/raw/`, encodings `utf-8-sig`/`latin-1`, campos extras em `Demais_Dados`, números em padrão PT-BR e EN-US, e códigos de aviário alfanuméricos.
4. **Observabilidade e Governança:**
   - Banco SQLite (`db/acertos.db`) sincronizado automaticamente com `data/raw/`.
   - Dashboard HTML interativo, pacote de issues (`issues_dev.md/.csv`), diff de duplicidades e bundle pronto para **NotebookLM**.
   - Agentes locais especializados (`.agents/skills/conferencia-acertos` e `.agents/skills/qa-analista-interfaces`) + grafo de código com `graphifyy`.
