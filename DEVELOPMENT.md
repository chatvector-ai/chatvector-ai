# Development notes

## notes on running backend
- cd backend
- python -m venv venv
- source venv/bin/activate            # On Mac
- venv\Scripts\activate               # On Windows
- pip install -r requirements.txt     # run if pr merged
- cd..                                # start backend from project root
- uvicorn backend.main:app --reload --port 8000

## notes on running frontend
- cd frontend
- npm install                         # run if pr merged
- npm run dev

## notes on creating a new feature branch
- git checkout main                   # switch to main
- git fetch upstream                  # get latest from upstream
- git merge upstream/main             # update your local main
- git push origin main                # update your fork’s main
- git checkout -b type/your-feature-name
- git branch                          #confirm you are in the new branch

## notes on submitting pr request
- git add .                   
- git commit -m "type: add your comment description"
- git push origin type/your-feature-name
- #go to fork and finalize PR request
