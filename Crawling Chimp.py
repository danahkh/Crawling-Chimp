import argparse
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

def scrape_directory(url, slow=False, output_file=None):
    # Send a GET request to the URL
    response = requests.get(url)
    
    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        # Parse the HTML content of the page using BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract and visit directories within the provided link
        base_url = urlparse(url).scheme + '://' + urlparse(url).netloc
        visited_links = set()
        output_links = set()
        
        def visit_link(link):
            if link not in visited_links:
                visited_links.add(link)
                print("Visiting link:", link)
                response = requests.get(link)
                if response.status_code == 200:
                    # You can add more processing logic here if needed
                    print("Successfully visited link:", link)
                    if slow:
                        import time
                        time.sleep(1)  # Sleep for 1 second to slow down requests
                    soup = BeautifulSoup(response.content, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        absolute_url = urljoin(link, a['href'])
                        if urlparse(absolute_url).netloc == urlparse(url).netloc and absolute_url not in visited_links:
                            visit_link(absolute_url)
                            output_links.add(absolute_url)
                else:
                    print("Error visiting link:", link)
        
        # Start visiting links
        visit_link(url)
        
        # Save output links to the specified output file
        if output_file:
            with open(output_file, 'w') as f:
                f.write('\n'.join(output_links))
                print(f"Output links saved to '{output_file}'")
    else:
        print("Error:", response.status_code)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Directory Scraper')
    parser.add_argument('-u', '--url', type=str, required=True, help='URL to scrape')
    parser.add_argument('-s', '--slow', action='store_true', help='Slow down requests')
    parser.add_argument('-f', '--output-file', type=str, help='Output file to save the output links')
    args = parser.parse_args()
    
    scrape_directory(args.url, args.slow, args.output_file)
