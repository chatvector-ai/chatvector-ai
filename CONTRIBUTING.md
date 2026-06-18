# Contributing to ChatVector-AI

## 🤝 First Time Contributing? Welcome!

There is a range of tasks for beginners to more advanced developers

This guide will walk you through the process step-by-step.

- Watch our [Contributor Video Guide](https://www.loom.com/share/c41bdbff541f47d49efcb48920cba382)
- For initial project setup see -- \*\*[📘 Readme](README.md)

### Start Here:

1. **Check the issues tab: [`good first issue`](https://github.com/chatvector-ai/chatvector-ai/issues?q=is%3Aopen+is%3Aissue+label%3A%22good+first+issue%22)** - These are specially tagged for beginners
2. **Check the [Project Board](https://github.com/orgs/chatvector-ai/projects/2)** - See what's being worked on
3. **Found a bug?** Open an issue and fix it!
4. **Have an idea?** Start a [Discussion](https://github.com/chatvector-ai/chatvector-ai/discussions/landing) first

### Still Unsure?

1. Comment on an issue
2. Ask for help in - [Discussions](https://github.com/chatvector-ai/chatvector-ai/discussions/landing)
3. We'll help you find the perfect first contribution

### Frontend demo contributions

If you're looking to contribute to the UI or user experience:
- Frontend work lives in `frontend-demo/` (a Next.js application).
- Good filters on the issues tab: `good first issue`, `frontend-demo`, `Frontend`, `beginner-friendly`.
- **Typical verify steps for frontend PRs:**
  - Run `npm run build` and `npm run lint` in `frontend-demo/`.
  - Manual check in the browser when UI behavior changes.
- For setup details, see [frontend-demo/README.md](frontend-demo/README.md) and [DEVELOPMENT.md → Frontend](DEVELOPMENT.md#frontend).

   ***

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

**Python:**

```python
# 👍 Good - Type hints and docstrings
def process_document_chunks(document_text: str) -> list[str]:
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
Follow the branching workflow described here:

📄 See: `development.md → Creating a new feature branch`

This document focuses on contribution rules and expectations.
```

### 2. Open Pull Request

1. Go to YOUR fork: github.com/YOUR_USERNAME/chatvector-ai
2. Look for: "Your recently pushed branches: feat/your-feature-name"
3. Click "Compare & pull request"
4. This creates PR from your fork → original repo

### 3. Fill PR Description

```
## What does this PR do?

## How was it tested?
- [ ] Tested locally with FastAPI `/docs`
- [ ] Checked existing functionality still works

## Screenshots (if UI changes):
```

🎯 Before Submitting

1. Run the test suite and confirm it passes: `make tests` (Docker) or `cd backend && pytest tests/ -v`
2. Test your changes manually using FastAPI `/docs`
3. Verify existing functionality still works
4. Check your code runs without errors
5. Update documentation if needed
