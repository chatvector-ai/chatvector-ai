# Contributing to ChatVector-AI

## 🤝 First Time Contributing? Welcome!

There is a range of tasks for beginners to more advanced developers

This guide will walk you through the process step-by-step.

- Watch our [Contributor Video Guide](https://www.loom.com/share/c41bdbff541f47d49efcb48920cba382) 
- For initial project setup see -- **[📘 Readme](README.md) -- [🎥 Setup Video](https://www.loom.com/share/8635d7e0a5a64953a4bf028360b74e25)

### Start Here:

1. **Check the issues tab: [`good first issue`](https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)** - These are specially tagged for beginners
2. **Check the [Project Board](https://github.com/orgs/chatvector-ai/projects/2)** - See what's being worked on
3. **Found a bug?** Open an issue and fix it!
4. **Have an idea?** Start a [Discussion](https://github.com/chatvector-ai/chatvector-ai/discussions/landing) first

### Still Unsure?

1. Comment on an issue
2. Ask for help in - [Discussions](https://github.com/chatvector-ai/chatvector-ai/discussions/landing)
3. We'll help you - find the perfect first contribution

  ---

## 📝 Branch and Commit Naming Convention

**Format:** `type/description`

**Types:**
- `feat/` - New features (e.g., `feat/add-dark-mode`)
- `fix/` - Bug fixes (e.g., `fix/upload-error-handling`)
- `docs/` - Documentation (e.g., `docs/update-readme`)
- `refactor/` - Code restructuring (e.g., `refactor/backend-modules`)



Quick checklist:
- Branch name follows convention
- Commits are focused and descriptive

Maintainers should review and merge according to project policy.

---

## Variable Naming 

**TypeScript/JavaScript:**
```javascript
// 👍 Good - Clear and descriptive
const uploadedDocuments = []
const handleFileUpload = () => {}

// 👎 Avoid - Too vague
const docs = []
const upload = () => {}
```

**Python:**
```python
# 👍 Good - Type hints and docstrings
def process_document_chunks(document_text: str) -> List[str]:
    """Split document into chunks for processing."""
    pass

# 👎 Avoid - Unclear purpose
def chunk(
```

---

## PR Process
**Check the [Readme](https://github.com/chatvector-ai/chatvector-ai/blob/main/README.md)** - For instructions on project setup

### 1. Create Your Feature Branch
```
**First, fork & clone the repo.** Then, from your local clone:
# Add the main project as "upstream" (do this once)
git remote add upstream https://github.com/chatvector-ai/chatvector-ai.git

# Sync your local main with the latest upstream code
git checkout main
git fetch upstream
git merge upstream/main

# Update your fork's main so it stays in sync
git push origin main

# Create and switch to your feature branch
git checkout -b feat/your-feature-name
```
### 2. Make & Commit Your Changes
```
# Make your code changes...

# Stage and commit
git add .
git commit -m "feat: add your feature description"
```
### 3. Push to Your Fork
```
# Push to YOUR fork (origin)
git push origin feat/your-feature-name
```

### 4. Open Pull Request
1. Go to YOUR fork: github.com/YOUR_USERNAME/chatvector-ai
2. Look for: "Your recently pushed branches: feat/your-feature-name"
3. Click "Compare & pull request"
4. This creates PR from your fork → original repo

### 5. Fill PR Description
```
## What does this PR do?

## How was it tested?
- [ ] Tested locally with FastAPI `/docs`
- [ ] Checked existing functionality still works

## Screenshots (if UI changes):
```

🎯 Before Submitting
1. Test your changes manually using FastAPI /docs
2. Verify existing functionality still works
3. Check your code runs without errors
4. Update documentation if needed
