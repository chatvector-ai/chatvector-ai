# Development Guide

This guide is intended as a quick reference for common development workflows
(e.g. starting servers, creating branches, submitting PRs). Initial setup is
covered in the main README.


## 1. Running the backend

```
cd backend
## mac/linux source venv/bin/activate
or    
## venv\Scripts\activate
pip install -r requirements.txt        # run if dependencies changed
cd ..
uvicorn backend.main:app --reload --port 8000
``` 

## 2. Running the frontend

```
cd frontend
npm install
npm run dev
```

## 3. Creating a new feature branch (OSS workflow)
Always branch from an up-to-date main.

```
git checkout main
git fetch upstream
git pull upstream main
git push origin main
git checkout -b type/your-feature-name
git branch
```

## 4. Submitting a pull request
Before committing, ensure your branch is rebased on the latest main:

```
git fetch upstream
git rebase upstream/main

# Resolve any conflicts, then:
git add .
git commit -m "type: concise description of change"
git push --force-with-lease origin type/your-feature-name
```

## Open a pull request from:
```
your-fork:type/your-feature-name → upstream:main
```