# Velox: Smart Collateral Credit Rail on BNB Chain

Velox is a **BNB Chain-first, non-custodial BNPL and Web3 credit layer** built for real-world checkout and repayment behavior.
Users lock on-chain collateral, merchants get paid upfront, and credit risk is managed through transparent safety rules, partial recovery, and explainable ML signals.

## Quick Start (One Command)

### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy Bypass -File .\setup_and_run.ps1
```
Optional (skip dependency reinstall):
```powershell
powershell -ExecutionPolicy Bypass -File .\setup_and_run.ps1 -SkipInstall
```

### macOS/Linux (Bash)
```bash
bash ./setup_and_run.sh
```
Optional (skip dependency reinstall):
```bash
bash ./setup_and_run.sh --skip-install
```

### What this does
1. Creates `.venv` if needed.
2. Installs backend dependencies from `backend/requirement.txt`.
3. Installs frontend dependencies in `ping_masters_ui/`.
4. Starts FastAPI backend + Angular frontend together.

After startup:
- Backend: `http://127.0.0.1:8000/docs`
- Frontend: `http://localhost:4200`

---

## Why Velox Matters (Hackathon Pitch)

### Problem
BNPL and crypto lending systems still struggle with:
- Custody risk
- Poor liquidation UX
- Opaque recovery behavior
- Weak merchant trust in collateral guarantees

### Velox Approach
Velox introduces a **shared smart-collateral layer** on BNB Chain:
- Borrower locks collateral in a verifiable vault.
- Merchant is settled upfront (test settlement flow integrated).
- Borrower repays in EMI/installments.
- If risk increases, system nudges and recommends top-up early.
- If default happens, system attempts **partial recovery** (only required amount), not full seizure.

### BNB Chain Focus
- Built for **BSC + opBNB** integration paths.
- Smart contract addresses and proof data integrated in backend APIs.
- Designed for high-throughput, low-cost on-chain credit interactions.

---

## How Judges Can Score Velox Fast

| Criteria | What Velox demonstrates |
|---|---|
| Design & Usability | Clean borrower flow, wallet + loan dashboard, explainability panel, proof timeline |
| Scalability | Modular services, model layer, Firestore repositories, config-driven policies |
| Innovation | Smart-collateral BNPL, partial liquidation, risk-driven nudges, dynamic deposit recommendation |
| Open Source | Documented APIs, reproducible setup scripts, structured ML scripts/artifacts |
| Integration | Firebase, Razorpay (test mode), BNB chain/web3 integration, market data feeds |

---

## Product User Flow

```mermaid
flowchart TB
    U[Borrower]

    subgraph L1[Layer 1 Identity and Access]
        A1[Sign in with Firebase]
        A2[Profile loaded with preferred currency]
        A3[Wallet linked and ownership verified]
        A1 --> A2 --> A3
    end

    subgraph L2[Layer 2 Credit Entry]
        B1[Create BNPL request]
        B2[Eligibility with KYC and AML checks]
        B3[EMI schedule generated]
        B1 --> B2 --> B3
    end

    subgraph L3[Layer 3 Collateral and Merchant Execution]
        C1[Collateral locked in BNB chain vault]
        C2[Merchant settlement initiated]
        C3[On chain proof and event timeline recorded]
        C1 --> C2 --> C3
    end

    subgraph L4[Layer 4 Repayment Intelligence]
        D1[Safety meter updates]
        D2[Risk score and default probability]
        D3[Dynamic top up recommendation]
        D4{User action before due date}
        D1 --> D2 --> D3 --> D4
    end

    subgraph L5[Layer 5 Collections and Resolution]
        E1[Installment paid on time]
        E2[Grace window and reminder nudges]
        E3[Partial recovery for missed dues]
        E4[Dispute and refund handling]
        E5[Loan closure and collateral release]
    end

    U --> A1
    A3 --> B1
    B3 --> C1
    C3 --> D1
    D4 -- Repay or top up --> E1
    D4 -- Missed payment --> E2
    E2 --> E4
    E2 --> E3
    E1 --> E5
    E3 --> E5
    E4 --> E5
```

## Tech Stack and Integration Flow

```mermaid
flowchart TB
    subgraph Client[Client Layer]
        UI[Angular Frontend]
        AUTH[Firebase Auth]
    end

    subgraph API[Velox Backend]
        ROUTERS[FastAPI Routers]
        BNPL[BNPL Feature Service]
        RISK[Risk + ML Orchestrator]
        LEDGER[Events and Audit Layer]
    end

    subgraph Data[Data and Config]
        FIRE[(Cloud Firestore)]
        CFG[config.yml]
        MLART[ML Artifacts]
    end

    subgraph ChainAndExternal[Chain and Integrations]
        BNB[BSC / opBNB Contracts]
        RZP[Razorpay Test APIs]
        MKT[Public Market Data APIs]
    end

    AUTH --> UI
    UI --> ROUTERS
    ROUTERS --> BNPL
    ROUTERS --> RISK
    BNPL --> FIRE
    RISK --> FIRE
    RISK --> MLART
    BNPL --> LEDGER
    BNPL --> BNB
    BNPL --> RZP
    RISK --> MKT
    ROUTERS --> CFG
```

---

## Current Feature Highlights

### Core credit + collateral
- Collateral lock and top-up
- BNPL plan creation and installment schedule
- Safety meter (health factor + status)
- Grace and recovery workflows
- Partial recovery handling
- Audit-friendly event trail

### Smart risk layer
- Rule-based risk score
- ML-backed risk/deposit inference endpoints
- Dynamic deposit recommendation (policy + model mode)
- Explainability payload for user-facing trust

### Merchant + trust
- Merchant settlement simulation
- Public proof payload with contract references and timeline

---

## Documentation Index

- API documentation: [backend/API_DOCUMENTATION.md](backend/API_DOCUMENTATION.md)
- Solidity/API mapping: [backend/SOLIDITY_API_DOCUMENTATION.md](backend/SOLIDITY_API_DOCUMENTATION.md)
- Firestore storage map: [backend/FIREBASE_STORAGE.md](backend/FIREBASE_STORAGE.md)
- User flow notes: [user_flow.md](user_flow.md)
- Architecture Diagram: [backend/ARCHITECTURE.md](backend/ARCHITECTURE.md)

---

## Repository Structure

```text
backend/            FastAPI app, services, models, route handlers
ping_masters_ui/    Angular frontend
contracts/          Solidity contracts and chain integration scripts
ml/                 ML modules, artifacts, and inference helpers
```

---

## Manual Run (Fallback)

### Backend
```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r .\backend\requirement.txt
.\.venv\Scripts\python .\backend\main.py
```

### Frontend
```powershell
cd .\ping_masters_ui
npm install
npm start
```

---

## 60-Second Judge Demo Script

1. Create a loan plan and lock collateral.
2. Show merchant settlement/proof data.
3. Open safety meter + risk tier + recommendation.
4. Trigger repayment/default simulation.
5. Show partial recovery and event proof timeline.
6. Close with auditability + scalability architecture.

---

## Notes

- Runtime config is centralized in `backend/config.yml`.
- Razorpay integration is configured for test-mode credentials.
- Python 3.10+ is recommended for dependency compatibility.
