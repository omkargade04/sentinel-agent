## Sentinel: The bug slayer
"No Bugs will be tolerated"

![altext](https://external-preview.redd.it/SHNtughQ3UZw2b-Gekke89Ifwh4M4d9msKM8ysuiYAk.gif?auto=webp&s=329dfb4f1d6dffb0b0c51dccae318f8ee753ac0f)

## 📌 Overview
Sentinel is an AI powered Code Reviewer Agent that tracks PR, reviews them and detects potential bugs

## 🚀 Installation & Setup

### Prerequisites
- Python (>=3.11)
- [Poetry](https://python-poetry.org/) for dependency management

### 1️⃣ Clone the Repository
```sh
git clone git@github.com:omkargade04/sentinel-agent.git
cd sentinel-agent
```

### 2️⃣ Install Dependencies
```sh
make install
```

### 3️⃣ Activate Virtual Environment
```sh
poetry shell
```

### 4️⃣ Run the Application
```sh
python -m src.main

or

uvicorn src.main:app --reload
```

### Run via Docker
```
- docker compose down
- docker compose down -v
- docker compose up --build
```