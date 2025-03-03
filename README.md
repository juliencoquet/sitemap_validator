# Sitemap validator
This script validates a remote sitemap URL and can proceed to submit them with Google Search Console for indexing.
Not perfect so do make sure to provide comments & suggestions.

# Installation
Setup command: `sh ./run.sh`

This script will create a virtual Python environment using `venv`, install the dependencies and run the validator script. Edit the `run.sh` script to avoid re-installing the whole setup with each run. 

The script will also submit the sitemap to Google Search Console if the `--submit-to-google` flag is set

For this to work, you need to provide a valid Google API credentials file in the `creds.json` file. Don't forget to add the email address associated with the GCP service account as Owner in your Search Console property.

# Usage
You can run the validator script by pointing to the sitemap.xml file of your choice (assuming you own the site)
`./bin/python3 sitemap_validator.py https://yoursite.com/sitemap.xml --submit-to-google --google-credentials creds.json`
