import argparse
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
from urllib.robotparser import RobotFileParser
from collections import deque
import logging
import os
from datetime import datetime
import json
import base64

def setup_logging(log_level="INFO", log_file=None):
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    
    # Configure logging level
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Setup handlers
    handlers = [logging.StreamHandler()]
    
    if log_file:
        # Create logs directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
    
    logging.basicConfig(
        level=level,
        format=log_format,
        handlers=handlers,
        force=True
    )
    
    return logging.getLogger(__name__)

def load_credentials(cred_file=None, username=None, password=None):
    """Load credentials from file or parameters"""
    credentials = {}
    
    if cred_file and os.path.exists(cred_file):
        try:
            with open(cred_file, 'r', encoding='utf-8') as f:
                cred_data = json.load(f)
                credentials.update(cred_data)
        except Exception as e:
            logging.error(f"Error loading credentials file: {e}")
    
    # Command line credentials override file credentials
    if username and password:
        credentials['username'] = username
        credentials['password'] = password
    
    return credentials

def setup_session(credentials=None, headers=None):
    """Setup requests session with credentials and headers"""
    session = requests.Session()
    
    # Default headers
    default_headers = {
        'User-Agent': 'CrawlingChimp/2.0 (Educational Web Crawler)',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    # Add custom headers if provided
    if headers:
        default_headers.update(headers)
    
    session.headers.update(default_headers)
    
    # Setup authentication if credentials provided
    if credentials:
        if 'username' in credentials and 'password' in credentials:
            # Basic authentication
            session.auth = (credentials['username'], credentials['password'])
            logging.info("Basic authentication configured")
        
        elif 'token' in credentials:
            # Token-based authentication
            session.headers['Authorization'] = f"Bearer {credentials['token']}"
            logging.info("Token authentication configured")
        
        elif 'api_key' in credentials:
            # API key authentication
            session.headers['X-API-Key'] = credentials['api_key']
            logging.info("API key authentication configured")
        
        # Session cookies if provided
        if 'cookies' in credentials:
            session.cookies.update(credentials['cookies'])
            logging.info("Session cookies configured")
    
    return session

def visit_link(url, visited_links, output_links, queue, session, parsed_base_url, depth, max_depth, slow, logger):
    """Visit a single link and extract new links"""
    if url in visited_links or depth > max_depth:
        return
    
    visited_links.add(url)
    logger.info(f"Crawling: {url} (depth: {depth})")
    
    try:
        response = session.get(url, timeout=10)
        response.raise_for_status()
        
        # Check if it's HTML content
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' not in content_type:
            logger.warning(f"Skipping non-HTML content: {url}")
            return
        
        # Parse content
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract links
        links_found = 0
        for link_tag in soup.find_all('a', href=True):
            href = link_tag['href']
            absolute_url = urljoin(url, href)
            
            # Clean up URL (remove fragments)
            parsed_url = urlparse(absolute_url)
            clean_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
            if parsed_url.query:
                clean_url += f"?{parsed_url.query}"
            
            # Check if link is within same domain
            if urlparse(clean_url).netloc == parsed_base_url.netloc:
                if clean_url not in visited_links and clean_url not in output_links:
                    output_links.add(clean_url)
                    if depth < max_depth:
                        queue.append((clean_url, depth + 1))
                    links_found += 1
        
        logger.info(f"Found {links_found} new links on {url}")
        
        # Respect server by slowing down if requested
        if slow:
            time.sleep(1)
        else:
            time.sleep(0.1)  # Small delay to be respectful
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error crawling {url}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error crawling {url}: {e}")

def scrape_directory(url, slow=False, output_file=None, max_depth=3, max_pages=100, 
                    credentials=None, log_level="INFO", log_file=None, custom_headers=None):
    """Main crawling function with enhanced features"""
    
    # Setup logging
    logger = setup_logging(log_level, log_file)
    
    # Validate URL
    try:
        parsed_url = urlparse(url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise ValueError("Invalid URL provided")
    except Exception as e:
        logger.error(f"URL validation error: {e}")
        return
    
    # Check robots.txt
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    robots_url = urljoin(base_url, '/robots.txt')
    
    try:
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        if not rp.can_fetch('*', url):
            logger.warning(f"Robots.txt disallows crawling {url}")
            # Continue anyway but log the warning
    except Exception as e:
        logger.warning(f"Could not read robots.txt: {e}")
    
    # Setup session with credentials
    session = setup_session(credentials, custom_headers)
    
    # Attempt to login to the site if credentials are provided
    if credentials and ('username' in credentials and 'password' in credentials):
        logger.info("Attempting form-based login")
        login_successful = login_to_site(session, base_url, credentials, logger)
        if login_successful:
            logger.info("Login successful")
        else:
            logger.warning("Login failed or not required")
    
    # Initialize tracking variables
    visited_links = set()
    output_links = set()
    queue = deque([(url, 0)])  # (url, depth)
    pages_crawled = 0
    start_time = datetime.now()
    
    logger.info(f"Starting crawl of {url}")
    logger.info(f"Parameters: max_depth={max_depth}, max_pages={max_pages}, slow={slow}")
    
    # Add the starting URL to output
    output_links.add(url)
    
    while queue and pages_crawled < max_pages:
        current_url, depth = queue.popleft()
        
        if current_url in visited_links or depth > max_depth:
            continue
        
        visit_link(current_url, visited_links, output_links, queue, session, 
                  parsed_url, depth, max_depth, slow, logger)
        pages_crawled += 1
        
        # Progress update every 10 pages
        if pages_crawled % 10 == 0:
            logger.info(f"Progress: {pages_crawled} pages crawled, {len(output_links)} links found")
    
    # Calculate crawling time
    end_time = datetime.now()
    duration = end_time - start_time
    
    logger.info(f"Crawling completed in {duration}")
    logger.info(f"Total pages crawled: {pages_crawled}")
    logger.info(f"Total unique links found: {len(output_links)}")
    
    # Save results
    if output_file:
        try:
            # Create output directory if it doesn't exist
            output_dir = os.path.dirname(output_file)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Crawling results for {url}\n")
                f.write(f"# Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Duration: {duration}\n")
                f.write(f"# Pages crawled: {pages_crawled}\n")
                f.write(f"# Links found: {len(output_links)}\n")
                f.write(f"# Max depth: {max_depth}\n\n")
                
                for link in sorted(output_links):
                    f.write(f"{link}\n")
            
            logger.info(f"Results saved to '{output_file}'")
        except Exception as e:
            logger.error(f"Error saving to file: {e}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"CRAWLING SUMMARY")
    print(f"{'='*60}")
    print(f"Starting URL: {url}")
    print(f"Pages crawled: {pages_crawled}")
    print(f"Unique links found: {len(output_links)}")
    print(f"Max depth: {max_depth}")
    print(f"Duration: {duration}")
    print(f"{'='*60}")
    
    return output_links

def create_sample_credentials_file(filename="credentials.json"):
    """Create a sample credentials file"""
    sample_creds = {
        "username": "your_username",
        "password": "your_password",
        "token": "your_bearer_token",
        "api_key": "your_api_key",
        "cookies": {
            "session_id": "your_session_id",
            "auth_token": "your_auth_token"
        }
    }
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(sample_creds, f, indent=2)
    
    print(f"Sample credentials file created: {filename}")
    print("Edit this file with your actual credentials.")

def save_session(session, filename="session.json"):
    """Save session cookies to file"""
    try:
        cookies_dict = {}
        for cookie in session.cookies:
            cookies_dict[cookie.name] = cookie.value
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(cookies_dict, f, indent=2)
        
        print(f"Session saved to {filename}")
    except Exception as e:
        print(f"Error saving session: {e}")

def load_session(session, filename="session.json"):
    """Load session cookies from file"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                cookies_dict = json.load(f)
            
            for name, value in cookies_dict.items():
                session.cookies.set(name, value)
            
            print(f"Session loaded from {filename}")
            return True
    except Exception as e:
        print(f"Error loading session: {e}")
    return False

def login_to_site(session, base_url, credentials, logger):
    """Attempt to login to the website using form-based authentication"""
    if not credentials or 'username' not in credentials or 'password' not in credentials:
        logger.info("No credentials provided for form-based login")
        return False
    
    try:
        # Common login page patterns
        login_urls = [
            f"{base_url}/login",
            f"{base_url}/signin",
            f"{base_url}/auth/login",
            f"{base_url}/account/login",
            f"{base_url}/user/login"
        ]
        
        login_page_url = None
        login_response = None
        
        # Try to find the login page
        for url in login_urls:
            try:
                response = session.get(url, timeout=10)
                if response.status_code == 200:
                    login_page_url = url
                    login_response = response
                    logger.info(f"Found login page at: {url}")
                    break
            except:
                continue
        
        if not login_page_url:
            logger.warning("Could not find login page")
            return False
        
        # Parse login form
        soup = BeautifulSoup(login_response.content, 'html.parser')
        
        # Find the login form
        login_form = soup.find('form')
        if not login_form:
            logger.warning("No login form found on the page")
            return False
        
        # Get form action and method
        form_action = login_form.get('action', '')
        if form_action.startswith('/'):
            form_action = base_url + form_action
        elif not form_action.startswith('http'):
            form_action = login_page_url
        
        form_method = login_form.get('method', 'post').lower()
        
        # Build form data
        form_data = {}
        
        # Debug: Log all form fields found
        all_inputs = login_form.find_all('input')
        logger.info(f"Found {len(all_inputs)} input fields in login form")
        for inp in all_inputs:
            logger.debug(f"Input field: name='{inp.get('name', '')}', type='{inp.get('type', 'text')}', id='{inp.get('id', '')}'")
        
        # Find input fields
        for input_field in login_form.find_all('input'):
            input_name = input_field.get('name', '')
            input_type = input_field.get('type', 'text').lower()
            input_value = input_field.get('value', '')
            input_id = input_field.get('id', '')
            
            if input_name:
                # Check for username/email fields
                if input_type in ['email', 'text'] and any(keyword in input_name.lower() for keyword in ['user', 'email', 'login', 'account']):
                    form_data[input_name] = credentials['username']
                elif input_type in ['email', 'text'] and any(keyword in input_id.lower() for keyword in ['user', 'email', 'login', 'account']):
                    form_data[input_name] = credentials['username']
                # Check for password fields
                elif input_type == 'password':
                    form_data[input_name] = credentials['password']
                # Handle hidden fields and tokens
                elif input_type in ['hidden', 'token']:
                    form_data[input_name] = input_value
                elif input_type == 'checkbox' and input_field.get('checked'):
                    form_data[input_name] = input_value or 'on'
                # Handle submit buttons
                elif input_type == 'submit' and input_value:
                    form_data[input_name] = input_value
        
        # Also check for common field names if not found automatically
        if not any(credentials['username'] in str(v) for v in form_data.values()):
            # Try common username field names
            common_username_fields = ['username', 'user', 'email', 'login', 'userid', 'user_email', 'account', 'un', 'uid']
            for field in common_username_fields:
                username_input = login_form.find('input', {'name': field}) or login_form.find('input', {'id': field})
                if username_input:
                    form_data[field] = credentials['username']
                    break
        
        if not any('password' in str(v) for v in form_data.values()):
            # Try common password field names
            common_password_fields = ['password', 'pass', 'pwd', 'passwd', 'pw', 'user_password']
            for field in common_password_fields:
                password_input = login_form.find('input', {'name': field}) or login_form.find('input', {'id': field})
                if password_input:
                    form_data[field] = credentials['password']
                    break
        
        logger.info(f"Attempting login with form data: {list(form_data.keys())}")
        
        # Submit login form
        if form_method == 'get':
            login_result = session.get(form_action, params=form_data, timeout=10)
        else:
            login_result = session.post(form_action, data=form_data, timeout=10)
        
        # Check if login was successful
        # Look for indicators of successful login
        success_indicators = [
            'dashboard', 'welcome', 'logout', 'profile', 'account',
            'home', 'main', 'index', 'admin', 'user'
        ]
        
        failure_indicators = [
            'error', 'invalid', 'incorrect', 'failed', 'denied',
            'login', 'signin', 'authentication'
        ]
        
        response_text = login_result.text.lower()
        response_url = login_result.url.lower()
        
        # Check for success indicators
        success_found = any(indicator in response_text or indicator in response_url 
                          for indicator in success_indicators)
        
        # Check for failure indicators
        failure_found = any(indicator in response_text 
                          for indicator in failure_indicators)
        
        # Additional checks
        if login_result.status_code == 200:
            if success_found and not failure_found:
                logger.info("Login appears successful")
                return True
            elif 'login' not in response_url and 'signin' not in response_url:
                logger.info("Login likely successful (redirected away from login page)")
                return True
        
        logger.warning("Login may have failed - continuing anyway")
        return False
        
    except Exception as e:
        logger.error(f"Error during login attempt: {e}")
        return False

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Crawling Chimp - Enhanced Recursive Web Crawler')
    parser.add_argument('-u', '--url', type=str, required=True, help='URL to scrape')
    parser.add_argument('-s', '--slow', action='store_true', help='Slow down requests (1 second delay)')
    parser.add_argument('-f', '--output-file', type=str, help='Output file to save the discovered links')
    parser.add_argument('-d', '--max-depth', type=int, default=3, help='Maximum crawling depth (default: 3)')
    parser.add_argument('-p', '--max-pages', type=int, default=100, help='Maximum pages to crawl (default: 100)')
    
    # Logging options
    parser.add_argument('--log-level', type=str, choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help='Logging level (default: INFO)')
    parser.add_argument('--log-file', type=str, help='Log file path (default: console only)')
    
    # Authentication options
    parser.add_argument('--cred-file', type=str, help='JSON file containing credentials')
    parser.add_argument('--username', type=str, help='Username for basic authentication')
    parser.add_argument('--password', type=str, help='Password for basic authentication')
    parser.add_argument('--create-cred-template', action='store_true', 
                       help='Create a sample credentials file template')
    parser.add_argument('--save-session', type=str, help='Save session cookies to file')
    parser.add_argument('--load-session', type=str, help='Load session cookies from file')
    
    # Custom headers
    parser.add_argument('--headers', type=str, help='Custom headers as JSON string')
    
    args = parser.parse_args()
    
    # Create credentials template if requested
    if args.create_cred_template:
        create_sample_credentials_file()
        exit(0)
    
    # Load credentials
    credentials = load_credentials(args.cred_file, args.username, args.password)
    
    # Parse custom headers if provided
    custom_headers = None
    if args.headers:
        try:
            custom_headers = json.loads(args.headers)
        except json.JSONDecodeError as e:
            print(f"Error parsing custom headers: {e}")
            exit(1)
    
    # Set default log file with timestamp if not specified
    log_file = args.log_file
    if not log_file and args.log_level == 'DEBUG':
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"logs/crawling_log_{timestamp}.log"
    
    # Run the crawler
    result = scrape_directory(
        url=args.url,
        slow=args.slow,
        output_file=args.output_file,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        credentials=credentials,
        log_level=args.log_level,
        log_file=log_file,
        custom_headers=custom_headers
    )
    
    # Save session if requested
    if args.save_session and result:
        # We need to modify scrape_directory to return the session
        print(f"Session save feature will be implemented in next version")