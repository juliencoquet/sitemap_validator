# Usage: ./run.sh

# This script will create a virtual environment, install the dependencies and run the validator script
# It will also submit the sitemap to Google Search Console if the --submit-to-google flag is set
# You need to provide a valid Google API credentials file in the creds.json file
# This next block can be commented out after the initial setup
python3 -m venv .
source bin/activate
./bin/pip install -r requirements.txt

# Run the validator script by pointing to the sitemap.xml file
./bin/python3 sitemap_validator.py https://yoursite.com/sitemap.xml --submit-to-google --google-credentials creds.json