import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import concurrent.futures
import time
from datetime import datetime
import argparse
import json
import google.oauth2.service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

class SitemapValidator:
    def __init__(self, sitemap_url, timeout=10, max_workers=5, user_agent="SitemapValidator/1.0"):
        self.sitemap_url = sitemap_url
        self.timeout = timeout
        self.max_workers = max_workers
        self.headers = {"User-Agent": user_agent}
        self.results = {
            "valid_urls": 0,
            "invalid_urls": 0,
            "total_urls": 0,
            "errors": []
        }
        self._all_processed_urls = []

    
    def validate(self):
        """Main validation method that orchestrates the process"""
        try:
            print(f"Fetching sitemap from: {self.sitemap_url}")
            response = requests.get(self.sitemap_url, headers=self.headers, timeout=self.timeout)
            
            if response.status_code != 200:
                self.results["errors"].append(f"Failed to fetch sitemap (HTTP {response.status_code})")
                return self.results
            
            # Check if it's XML
            content_type = response.headers.get('Content-Type', '')
            if 'xml' not in content_type.lower():
                self.results["errors"].append(f"Sitemap is not XML (Content-Type: {content_type})")
            
            urls = self._parse_sitemap(response.content)
            self.results["total_urls"] = len(urls)
            
            # Validate each URL
            self._validate_urls(urls)
            
            return self.results
            
        except Exception as e:
            self.results["errors"].append(f"Validation failed: {str(e)}")
            return self.results
    
    def _parse_sitemap(self, content):
        """Parse the XML sitemap and extract URLs"""
        urls = []
        root = ET.fromstring(content)
        
        # Define namespace mapping
        namespaces = {
            'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'
        }
        
        # Check if it's a sitemap index
        sitemap_tags = root.findall('.//sm:sitemap', namespaces)
        if sitemap_tags:
            print("This is a sitemap index file, processing child sitemaps...")
            for sitemap in sitemap_tags:
                loc = sitemap.find('./sm:loc', namespaces)
                if loc is not None and loc.text:
                    # Recursively validate each child sitemap
                    child_validator = SitemapValidator(loc.text, 
                        self.timeout, 
                        self.max_workers)
                    child_results = child_validator.validate()
                    
                    # Merge results
                    self.results["valid_urls"] += child_results["valid_urls"]
                    self.results["invalid_urls"] += child_results["invalid_urls"]
                    self.results["total_urls"] += child_results["total_urls"]
                    self.results["errors"].extend(child_results["errors"])
            
            return urls
        
        # Process regular sitemap
        url_tags = root.findall('.//sm:url', namespaces)
        for url in url_tags:
            loc = url.find('./sm:loc', namespaces)
            if loc is not None and loc.text:
                urls.append({
                    'loc': loc.text.strip(),
                    'lastmod': self._get_tag_text(url, './sm:lastmod', namespaces),
                    'changefreq': self._get_tag_text(url, './sm:changefreq', namespaces),
                    'priority': self._get_tag_text(url, './sm:priority', namespaces)
                })
        
        return urls
    
    def _get_tag_text(self, element, tag_path, namespaces):
        """Helper to extract text from an XML tag"""
        tag = element.find(tag_path, namespaces)
        return tag.text.strip() if tag is not None and tag.text else None
    
    def _validate_urls(self, urls):
        """Validate all URLs using a thread pool"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {executor.submit(self._check_url, url): url for url in urls}
            for future in concurrent.futures.as_completed(future_to_url):
                try:
                    future.result()
                except Exception as e:
                    self.results["errors"].append(f"Error during URL validation: {str(e)}")
    
    def _check_url(self, url_data):
        """Validate a single URL"""
        url = url_data['loc']
        url_result = url_data.copy()
        url_result['is_valid'] = False
        
        try:
            # Basic URL structure validation
            parsed = urlparse(url)
            if not all([parsed.scheme, parsed.netloc]):
                self.results["invalid_urls"] += 1
                self.results["errors"].append(f"Invalid URL structure: {url}")
                self._all_processed_urls.append(url_result)
                return
            
            # Check HTTP response
            print(f"Checking: {url}")
            response = requests.head(url, headers=self.headers, timeout=self.timeout, allow_redirects=True)
            
            # Fall back to GET if HEAD is not supported
            if response.status_code in [405, 404, 403]:
                response = requests.get(url, headers=self.headers, timeout=self.timeout)
            
            if 200 <= response.status_code < 300:
                self.results["valid_urls"] += 1
                url_result['is_valid'] = True
            else:
                self.results["invalid_urls"] += 1
                self.results["errors"].append(f"URL returned HTTP {response.status_code}: {url}")
                
        except requests.exceptions.RequestException as e:
            self.results["invalid_urls"] += 1
            self.results["errors"].append(f"Failed to connect to {url}: {str(e)}")
        
        self._all_processed_urls.append(url_result)

    def submit_to_google_indexing(self, credentials_file, batch_size=100):
        """
        Submit URLs from the sitemap to Google's Indexing API
        
        Args:
            credentials_file (str): Path to Google service account JSON credentials file
            batch_size (int): Number of URLs to submit in each batch
        
        Returns:
            dict: Results of the submission process
        """
        try:
            # Load credentials
            credentials = google.oauth2.service_account.Credentials.from_service_account_file(
                credentials_file,
                scopes=['https://www.googleapis.com/auth/indexing']
            )
            
            # Build the service
            service = build('indexing', 'v3', credentials=credentials)
            
            print(f"Submitting URLs to Google Search Console for indexing...")
            
            # Get all valid URLs
            urls_to_submit = []
            
            # In this example, we're using the validated URLs from our sitemap validation
            for url_data in self._get_valid_urls():
                urls_to_submit.append(url_data['loc'])
            
            total_urls = len(urls_to_submit)
            print(f"Found {total_urls} URLs to submit")
            
            # Process in batches
            successful = 0
            failed = 0
            errors = []
            
            for i in range(0, total_urls, batch_size):
                batch = urls_to_submit[i:i + batch_size]
                print(f"Processing batch {i//batch_size + 1}/{(total_urls + batch_size - 1)//batch_size}")
                
                for url in batch:
                    try:
                        result = service.urlNotifications().publish(
                            body={"url": url, "type": "URL_UPDATED"}
                        ).execute()
                        
                        if "urlNotificationMetadata" in result:
                            successful += 1
                        else:
                            failed += 1
                            errors.append(f"Failed to submit {url}: Unexpected response")
                            
                    except HttpError as e:
                        failed += 1
                        error_details = json.loads(e.content.decode())
                        error_reason = error_details.get('error', {}).get('message', str(e))
                        errors.append(f"Failed to submit {url}: {error_reason}")
                    
                    # Avoid hitting API rate limits
                    time.sleep(0.2)
            
            return {
                "total_submitted": total_urls,
                "successful": successful,
                "failed": failed,
                "errors": errors
            }
                
        except Exception as e:
            return {
                "total_submitted": 0,
                "successful": 0,
                "failed": 0,
                "errors": [f"Submission process failed: {str(e)}"]
            }
    
    def _get_valid_urls(self):
        """Helper method to return only valid URLs from the validation results"""
        valid_urls = []
        
        for url_data in self._all_processed_urls:
            if url_data.get('is_valid', False):
                valid_urls.append(url_data)
        
        return valid_urls

def main():
    parser = argparse.ArgumentParser(description='Validate XML Sitemaps')
    parser.add_argument('sitemap_url', help='URL of the sitemap to validate')
    parser.add_argument('--timeout', type=int, default=10, help='Request timeout in seconds')
    parser.add_argument('--max-workers', type=int, default=5, help='Maximum number of concurrent workers')
    parser.add_argument('--user-agent', default="SitemapValidator/1.0", help='User agent string to use')
    parser.add_argument('--submit-to-google', action='store_true', help='Submit valid URLs to Google Search Console')
    parser.add_argument('--google-credentials', help='Path to Google service account credentials JSON file')
    parser.add_argument('--batch-size', type=int, default=100, help='Batch size for Google indexing API requests')
    args = parser.parse_args()
    
    start_time = time.time()
    validator = SitemapValidator(
        args.sitemap_url,
        timeout=args.timeout,
        max_workers=args.max_workers,
        user_agent=args.user_agent
    )
    
    results = validator.validate()
    
    # Print results
    print("\n" + "="*50)
    print(f"Sitemap Validation Results for {args.sitemap_url}")
    print("="*50)
    print(f"Total URLs: {results['total_urls']}")
    print(f"Valid URLs: {results['valid_urls']}")
    print(f"Invalid URLs: {results['invalid_urls']}")
    print(f"Validation completed in {time.time() - start_time:.2f} seconds")
    
    if results["errors"]:
        print("\nErrors found:")
        for error in results["errors"]:
            print(f"- {error}")
    
    # Submit to Google if requested
    if args.submit_to_google:
        if not args.google_credentials:
            print("\nError: Google credentials file is required for submission to Google Search Console")
        else:
            gsc_results = validator.submit_to_google_indexing(
                args.google_credentials,
                batch_size=args.batch_size
            )
            
            print("\n" + "="*50)
            print("Google Search Console Submission Results")
            print("="*50)
            print(f"Total URLs submitted: {gsc_results['total_submitted']}")
            print(f"Successful submissions: {gsc_results['successful']}")
            print(f"Failed submissions: {gsc_results['failed']}")
            
            if gsc_results["errors"]:
                print("\nSubmission errors:")
                for error in gsc_results["errors"][:10]:  # Show just the first 10 errors
                    print(f"- {error}")
                
                if len(gsc_results["errors"]) > 10:
                    print(f"... and {len(gsc_results['errors']) - 10} more errors")

if __name__ == "__main__":
    main()