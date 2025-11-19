# Contributing to Doctalk-AI

## 🤝 First Time Contributing? Welcome!

There is a range of tasks for beginners to more advanced developers

This guide will walk you through the process step-by-step.

## 🚀 How to Find Something to Do

### Start Here:

1. **Look for [`good first issue`](https://github.com/doctalk-ai/doctalk-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)** - These are specially tagged for beginners
2. **Check the [Project Board](https://github.com/orgs/doctalk-ai/projects/2)** - See what's being worked on
3. **Found a bug?** Open an issue and fix it!
4. **Have an idea?** Start a discussion first

### Still Unsure?

1. Comment on an issue - "I'd like to work on this!"
2. Ask for help in - [Discussions](https://github.com/doctalk-ai/doctalk-ai/discussions/landing)
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
**Check the [Readme](https://github.com/doctalk-ai/doctalk-ai?tab=readme-ov-file)** - For instructions on project setup

### 1. Create Your Feature Branch
```
# Add original repo as "upstream" (do this once)
git remote add upstream https://github.com/doctalk-ai/doctalk-ai.git

# Get latest changes from original
git checkout main
git pull upstream main

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
1. Go to YOUR fork: github.com/YOUR_USERNAME/doctalk-ai
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
