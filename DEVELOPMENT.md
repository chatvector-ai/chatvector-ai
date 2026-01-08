# Development Guide

This guide is intended as a quick reference for common development workflows
(e.g. starting servers, creating branches, submitting PRs). Initial setup is
covered in the main README. 

## 1. Running the backend

```bash
cd backend

# Activate virtual environment
# mac/linux
source venv/bin/activate
# Windows
venv\Scripts\activate

# Install dependencies (if requirements.txt changed)
pip install -r requirements.txt

# Return to project root
cd ..

# Launch backend server
uvicorn backend.main:app --reload --port 8000
```
## 2. Running the frontend

```bash
cd frontend
npm install
npm run dev
```

## 3. Creating a new feature branch (OSS workflow)
Always branch from an up-to-date main.

```bash
# 1. Switch to local main
git checkout main

# 2. Fetch and pull latest commits from upstream
git fetch upstream
git pull upstream main

# 3. Optional: update your fork's main
git push origin main

# 4. Create a new feature branch
git checkout -b type/your-feature-name

# 5. Confirm branch
git branch
```

## 4. Rebasing before submitting a pull request
Before opening a PR, ensure your feature branch is up-to-date with upstream main:

```bash
# Fetch latest upstream commits
git fetch upstream

# Ensure you are on your feature branch
git checkout type/your-feature-name

# Rebase onto upstream/main
git rebase upstream/main

# Resolve conflicts if any:
# 1. Edit conflicting files
# 2. git add <file>
# 3. git rebase --continue
# To abort if necessary: git rebase --abort

# Push updated branch to your fork
git push --force-with-lease origin type/your-feature-name
```

## 5. Submitting a pull request
Open a PR from:
```bash
your-fork:type/your-feature-name → upstream:main
```
- Review your changes and confirm CI/tests pass before merging

- Review the [Contributor Guide](CONTRIBUTING.md) for more details on creating/submitting PRs