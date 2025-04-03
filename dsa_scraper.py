import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from datetime import datetime
import logging
import re
import json
import traceback
from urllib.parse import urljoin, urlparse, parse_qs
from fake_useragent import UserAgent
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import io
from address_normalizer import AddressNormalizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('dsa_scraper.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class DSAScraper:
    def __init__(self, use_proxy: bool = False, proxy: Optional[str] = None, request_delay: float = 0.0):
        """Initialize the DSA scraper with optional proxy support."""
        self.base_url = "https://www.apps2.dgs.ca.gov/dsa/tracker/"
        self.session = self._create_session()
        self.debug_info = []
        self.use_proxy = use_proxy
        self.proxy = proxy
        self.request_delay = request_delay
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'start_time': datetime.now()
        }
        
    def _create_session(self) -> requests.Session:
        """Create a requests session with retries and rotating user agents."""
        session = requests.Session()
        
        # Configure retries
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set up rotating user agent
        ua = UserAgent()
        session.headers.update({
            'User-Agent': ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        return session

    def _make_request(self, url: str, method: str = 'get', data: Optional[Dict] = None, retries: int = 3) -> Optional[requests.Response]:
        """Make HTTP request with proxy support and error handling."""
        for attempt in range(retries):
            try:
                # Add delay between requests
                if self.request_delay > 0:
                    time.sleep(self.request_delay)

                kwargs = {}
                if self.use_proxy and self.proxy:
                    kwargs['proxies'] = {
                        'http': self.proxy,
                        'https': self.proxy
                    }
                
                if method.lower() == 'post':
                    response = self.session.post(url, data=data, **kwargs)
                else:
                    response = self.session.get(url, **kwargs)
                
                response.raise_for_status()
                self.stats['successful_requests'] += 1
                return response
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:  # Rate limited
                    wait_time = int(e.response.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limited. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                raise
            except Exception as e:
                logger.error(f"Request failed (attempt {attempt + 1}/{retries}): {str(e)}")
                if attempt == retries - 1:
                    self.stats['failed_requests'] += 1
                    raise
                time.sleep(2 ** attempt)  # Exponential backoff
                
        return None

    def get_project_list(self, client_id: str, progress_bar: Optional[Any] = None, status_text: Optional[Any] = None) -> List[Dict]:
        """Get list of all projects with enhanced error handling and debugging."""
        url = f"{self.base_url}ProjectList.aspx?ClientId={client_id}"
        
        try:
            response = self._make_request(url)
            if not response:
                return []
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Find the specific project table by ID
            table = soup.find('table', {'id': 'ctl00_MainContent_gdvsch'})
                    
            if not table:
                error_msg = "Project table not found in response"
                logger.error(error_msg)
                self.debug_info.append(error_msg)
                return []
                
            projects = []
            detailed_projects = []
            
            # Process each row in the table
            rows = table.find_all('tr')
            total_rows = len(rows)
            
            # Skip header row
            for i, row in enumerate(rows[1:], 1):
                try:
                    cells = row.find_all('td')
                    if len(cells) >= 3:
                        # Get the link from the first cell
                        link = cells[0].find('a')
                        if link and 'ApplicationSummary.aspx' in link.get('href', ''):
                            href = link.get('href', '')
                            
                            # Extract DSA AppId from the URL parameters
                            parsed_url = urlparse(href)
                            query_params = parse_qs(parsed_url.query)
                            origin_id = query_params.get('OriginId', [''])[0]
                            app_id = query_params.get('AppId', [''])[0]
                            dsa_appid = f"{origin_id} {app_id}" if origin_id and app_id else ""
                            
                            project = {
                                'Link': urljoin(self.base_url, href),
                                'DSA AppId': dsa_appid,
                                'PTN': '',  # Will be filled from detail page
                                'Project Name': cells[2].get_text(strip=True),
                                'Project Scope': '',
                                'Project Cert Type': '',
                                'Address': '',  # Will be filled from detail page
                                'City': '',     # Will be filled from detail page
                                'ZIP': ''       # Will be filled from detail page
                            }
                            
                            # Get project details
                            try:
                                basic_info, detailed_info = self.get_project_details(project['Link'])
                                if basic_info:
                                    project.update(basic_info)
                                    # Ensure address fields are copied from detailed_info if not in basic_info
                                    if detailed_info:
                                        for field in ['Address', 'City', 'ZIP']:
                                            if field not in basic_info and field in detailed_info:
                                                project[field] = detailed_info[field]
                                if detailed_info:
                                    detailed_project = project.copy()
                                    detailed_project.update(detailed_info)
                                    detailed_projects.append(detailed_project)
                            except Exception as e:
                                logger.error(f"Error getting details for project {project['Link']}: {str(e)}")
                            
                            projects.append(project)
                            
                            if progress_bar:
                                progress_bar.progress(i / (total_rows - 1))
                            if status_text:
                                status_text.text(f"Processing project {i} of {total_rows - 1}")
                            
                except Exception as e:
                    error_info = f"Error processing row {i}: {str(e)}\n{traceback.format_exc()}"
                    logger.error(error_info)
                    self.debug_info.append(error_info)
                    continue
                    
            return projects, detailed_projects
            
        except Exception as e:
            error_info = f"Error fetching project list: {str(e)}\n{traceback.format_exc()}"
            logger.error(error_info)
            self.debug_info.append(error_info)
            raise

    def get_project_details(self, url: str) -> Optional[Dict]:
        """Get project details with enhanced error handling and debugging."""
        try:
            # First get the application summary page
            response = self._make_request(url)
            if not response:
                return None, None
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Initialize both basic and detailed info dictionaries
            basic_info = {}
            detailed_info = {}
            
            # Look for PTN in the detail page
            ptn = ""
            ptn_cell = soup.find('td', string=re.compile(r'PTN\s+#:', re.I))
            if ptn_cell and ptn_cell.find_next('td'):
                ptn = ptn_cell.find_next('td').get_text(strip=True)
                basic_info['PTN'] = ptn
                detailed_info['PTN'] = ptn
            
            # Look for project name in a table cell
            project_name = ""
            name_cell = soup.find('td', string=re.compile(r'Project\s+Name:', re.I))
            if name_cell and name_cell.find_next('td'):
                project_name = name_cell.find_next('td').get_text(strip=True)
                basic_info['Project Name'] = project_name
                detailed_info['Project Name'] = project_name
            
            # Look for project scope in a table cell
            scope = ""
            scope_cell = soup.find('td', string=re.compile(r'Project\s+Scope:', re.I))
            if scope_cell and scope_cell.find_next('td'):
                scope = scope_cell.find_next('td').get_text(strip=True)
            
            basic_info['Project Scope'] = scope
            detailed_info['Project Scope'] = scope

            # Look for ZIP code
            zip_code = ""
            zip_cell = soup.find('td', string=re.compile(r'Zip:', re.I))
            if zip_cell and zip_cell.find_next('td'):
                zip_code = zip_cell.find_next('td').get_text(strip=True)
                detailed_info['ZIP'] = zip_code

            # Get certification info from the Project Certification page
            cert_type = ""
            try:
                # Extract AppId and OriginId from the current URL
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)
                origin_id = query_params.get('OriginId', [''])[0]
                app_id = query_params.get('AppId', [''])[0]
                
                if origin_id and app_id:
                    # Construct the Project Certification URL
                    cert_url = f"{self.base_url}ProjectCloseout.aspx?OriginId={origin_id}&AppId={app_id}"
                    cert_response = self._make_request(cert_url)
                    
                    if cert_response:
                        cert_soup = BeautifulSoup(cert_response.text, 'lxml')
                        
                        # Look for Last Certification Letter Type in any table cell
                        cert_type_cell = cert_soup.find('td', string=re.compile(r'Last Certification Letter Type:', re.I))
                        if cert_type_cell:
                            next_cell = cert_type_cell.find_next('td')
                            if next_cell:
                                cert_type = next_cell.get_text(strip=True)
                        
                        # If not found, look for specific certification patterns
                        if not cert_type:
                            cert_patterns = [
                                r'#\d+-Certification & Close of File(?:\s+Per EDU Code \d+\(\w+\)\s+OR\s+\d+\(\w+\))?',
                                r'DSA 301P Notification of Requirement for Certification',
                                r'#\d+-Close of File w/o Certification - Exceptions',
                                r'1 YR VOID'
                            ]
                            
                            for pattern in cert_patterns:
                                matches = cert_soup.find_all(string=re.compile(pattern, re.I))
                                if matches:
                                    cert_type = matches[0].strip()
                                    break
            except Exception as e:
                logger.error(f"Error getting certification details: {str(e)}")

            basic_info['Project Cert Type'] = cert_type
            detailed_info['Project Cert Type'] = cert_type
            
            # Collect detailed information
            field_mappings = {
                'Office ID:': 'Office ID',
                'Application #:': 'Application #',
                'File #:': 'File #',
                'PTN #:': 'PTN #',
                'OPSC #:': 'OPSC #',
                'Project Type:': 'Project Type',
                'Project Class:': 'Project Class',
                'Special Type:': 'Special Type',
                '# Of Incr:': 'Number of Increments',
                'Address:': 'Address',
                'City:': 'City',
                'Zip:': 'Zip',
                'Estimated Amt:': 'Estimated Amount',
                'Contracted Amt:': 'Contracted Amount',
                'Construction Change Document Amt:': 'Change Document Amount',
                'Final Project Cost:': 'Final Project Cost',
                'Adj Est.Date#1:': 'Adjustment Date 1',
                'Adj Est.Amt#1:': 'Adjustment Amount 1',
                'Adj Est.Date#2:': 'Adjustment Date 2',
                'Adj Est.Amt#2:': 'Adjustment Amount 2',
                'Received Date:': 'Received Date',
                'Approved Date:': 'Approved Date',
                'Approval Ext. Date:': 'Approval Extension Date',
                'Closed Date:': 'Closed Date',
                'Complete Submittal Received Date:': 'Complete Submittal Date'
            }
            
            # Extract all field values
            for field, key in field_mappings.items():
                field_cell = soup.find('td', string=re.compile(rf'^{field}$', re.I))
                if field_cell and field_cell.find_next('td'):
                    value = field_cell.find_next('td').get_text(strip=True)
                    if value:
                        detailed_info[key] = value
            
            # Get checkbox/indicator fields
            indicators = {
                'SB 575': 'SB 575',
                'New Campus': 'New Campus',
                'Modernization': 'Modernization',
                'Auto Fire Detection': 'Auto Fire Detection',
                'Sprinkler System': 'Sprinkler System',
                'Access Compliance': 'Access Compliance',
                'Fire & Life Safety': 'Fire & Life Safety',
                'Structural Safety': 'Structural Safety',
                'Field Review': 'Field Review',
                'CGS Review': 'CGS Review',
                'HPS': 'HPS'
            }
            
            for indicator, key in indicators.items():
                indicator_cell = soup.find('td', string=re.compile(rf'^{indicator}$', re.I))
                if indicator_cell:
                    # Check if there's an input checkbox and if it's checked
                    checkbox = indicator_cell.find_previous('input', {'type': 'checkbox'})
                    if checkbox and checkbox.get('checked'):
                        detailed_info[key] = 'Yes'
                    else:
                        detailed_info[key] = 'No'
            
            return basic_info, detailed_info
            
        except Exception as e:
            logger.error(f"Error getting project details from {url}: {str(e)}")
            return None, None

    def get_stats(self) -> Dict:
        """Get current scraping statistics."""
        stats = self.stats.copy()
        stats['elapsed_time'] = str(datetime.now() - stats['start_time'])
        return stats

def main():
    st.set_page_config(
        page_title="DSA Project Scraper",
        page_icon="🏗️",
        layout="wide"
    )
    
    # Header section with title and description
    st.title("🏗️ DSA Project Scraper")
    
    st.markdown("""
    ## Welcome to the DSA Project Data Tool
    
    This application helps you gather and organize project data from the Division of the State Architect (DSA) website. 
    It automatically collects project information, normalizes addresses, and presents the data in an organized Excel workbook.
    """)
    
    # Sidebar controls
    with st.sidebar:
        st.header("⚙️ Settings")
        client_id = st.text_input("Client ID", value="36-67")
        
        st.subheader("Request Delay")
        request_delay = st.slider(
            "Delay between requests (seconds)",
            min_value=0.0,
            max_value=1.0,
            value=0.0,
            step=0.1,
            help="Add delay between requests to avoid rate limiting (0 = no delay, 1 = 1 second delay)"
        )
        
        use_proxy = st.checkbox("Use Proxy")
        proxy = st.text_input("Proxy URL (optional)") if use_proxy else None
        
        st.markdown("---")
        st.markdown("### 📝 Notes")
        st.markdown("""
        - The scraper respects rate limits
        - Address normalization follows USPS standards
        - Data is cached for better performance
        """)

        st.markdown("---")
        st.markdown("### 📊 Output Format")
        st.markdown("""
        The data is organized into three comprehensive sheets:

        **Project List**
        - Basic project information
        - Normalized addresses
        - Project scope and certification details

        **Financial Details**
        - Cost estimates and final amounts
        - Important project dates
        - Location information

        **Technical Requirements**
        - Compliance specifications
        - Safety requirements
        - Project classifications
        """)

        st.markdown("---")
        st.markdown("### 🚀 Getting Started")
        st.markdown("""
        1. Enter your Client ID (default: 36-67)
        2. Adjust the request delay if needed
        3. Click "Start Scraping" to begin
        4. Download your Excel file when complete
        """)

        st.markdown("---")
        st.markdown("### ✨ Features")
        st.markdown("""
        - Automatic address normalization
        - Smart data organization
        - Excel export with formatted columns
        - Progress tracking
        - Cache system for better performance
        """)
    
    # Main content - Start button
    if st.button("🚀 Start Scraping", type="primary"):
        try:
            scraper = DSAScraper(use_proxy=use_proxy, proxy=proxy, request_delay=request_delay)
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            projects, detailed_projects = scraper.get_project_list(
                client_id=client_id,
                progress_bar=progress_bar,
                status_text=status_text
            )
            
            if projects:
                # Create DataFrames
                basic_df = pd.DataFrame(projects)
                # Ensure columns are in the correct order to match the image exactly
                basic_columns = ['Link', 'DSA AppId', 'PTN', 'Project Name', 'Project Scope', 'Project Cert Type', 'Address', 'City', 'ZIP']
                basic_df = basic_df.reindex(columns=basic_columns)
                
                # Create Raw Data DataFrame for address verification
                raw_columns = [
                    'DSA AppId', 'Project Name', 'Address', 'City', 'ZIP',
                    'Project Type', 'Project Class', 'Received Date'
                ]
                raw_df = pd.DataFrame(detailed_projects).reindex(columns=raw_columns)
                
                # Create Financial Details DataFrame
                financial_columns = [
                    'DSA AppId', 'Project Name', 'PTN',
                    'Estimated Amount', 'Contracted Amount', 'Change Document Amount', 'Final Project Cost',
                    'Received Date', 'Approved Date', 'Closed Date',
                    'Project Type', 'Project Class', 'Address', 'City'
                ]
                financial_df = pd.DataFrame(detailed_projects).reindex(columns=[col for col in financial_columns if col in pd.DataFrame(detailed_projects).columns])
                
                # Create Technical Requirements DataFrame
                technical_columns = [
                    'DSA AppId', 'Project Name', 'Project Type', 'Project Class',
                    'Access Compliance', 'Fire & Life Safety', 'Structural Safety',
                    'Auto Fire Detection', 'Sprinkler System', 'Field Review',
                    'CGS Review', 'HPS', 'Special Type', 'Number of Increments'
                ]
                technical_df = pd.DataFrame(detailed_projects).reindex(columns=[col for col in technical_columns if col in pd.DataFrame(detailed_projects).columns])
                
                # Address Normalization
                st.subheader("🏠 Address Normalization")
                with st.expander("Preview Address Normalization", expanded=True):
                    normalizer = AddressNormalizer()
                    
                    # Prepare addresses for batch normalization
                    addresses_to_normalize = []
                    for idx, row in basic_df.iterrows():
                        if pd.notna(row['Address']) and pd.notna(row['City']):
                            addresses_to_normalize.append({
                                'address': row['Address'],
                                'city': row['City'],
                                'zip': row['ZIP'] if pd.notna(row['ZIP']) else '',
                                'project_name': row['Project Name']
                            })
                    
                    # Show progress for address normalization
                    st.text("🔄 Normalizing addresses...")
                    progress_bar = st.progress(0)
                    
                    # Perform batch normalization
                    normalized_addresses = normalizer.normalize_batch(addresses_to_normalize)
                    
                    # Update the DataFrame with normalized addresses
                    normalized_df = basic_df.copy()
                    for idx, row in normalized_df.iterrows():
                        if pd.notna(row['Address']) and pd.notna(row['City']):
                            key = f"{row['Address']}, {row['City']}"
                            if pd.notna(row['ZIP']):
                                key += f" {row['ZIP']}"
                            
                            if key in normalized_addresses:
                                normalized = normalized_addresses[key]
                                parts = normalized.split(',')
                                if len(parts) >= 2:
                                    normalized_df.at[idx, 'Address'] = parts[0].strip()
                                    city_zip = parts[1].strip().split()
                                    if len(city_zip) >= 2:
                                        normalized_df.at[idx, 'City'] = ' '.join(city_zip[:-1])
                                        normalized_df.at[idx, 'ZIP'] = city_zip[-1]
                        
                        # Update progress
                        progress_bar.progress((idx + 1) / len(normalized_df))
                    
                    # Show changes
                    if normalized_addresses:
                        st.write("📋 The following addresses were normalized:")
                        changes_df = pd.DataFrame(
                            [(orig, norm) for orig, norm in normalized_addresses.items()],
                            columns=['Original Address', 'Normalized Address']
                        )
                        st.dataframe(changes_df, use_container_width=True)
                        
                        # Add analysis of city discrepancies
                        city_conflicts = []
                        for orig, norm in normalized_addresses.items():
                            orig_parts = orig.split(',')
                            norm_parts = norm.split(',')
                            if len(orig_parts) > 1 and len(norm_parts) > 1:
                                orig_city = orig_parts[1].strip()
                                norm_city = norm_parts[1].strip().split()[0]  # Take city without ZIP
                                if orig_city != norm_city:
                                    city_conflicts.append({
                                        'Address': orig_parts[0].strip(),
                                        'Original City': orig_city,
                                        'Normalized City': norm_city,
                                        'ZIP': norm_parts[1].strip().split()[-1] if len(norm_parts[1].strip().split()) > 1 else 'N/A'
                                    })
                        
                        if city_conflicts:
                            st.write("⚠️ Found city name discrepancies:")
                            conflicts_df = pd.DataFrame(city_conflicts)
                            st.dataframe(conflicts_df, use_container_width=True)
                        
                        # Option to use normalized addresses
                        if st.checkbox("Use normalized addresses in export", value=True):
                            basic_df = normalized_df
                    else:
                        st.write("✅ No addresses needed normalization.")
                    
                    # Show cache stats
                    cache_stats = normalizer.get_cache_stats()
                    st.write("📊 Cache Statistics:")
                    st.write(f"- Cached addresses: {cache_stats['size']}")
                    st.write(f"- Cache hits: {cache_stats['hits']}")
                    st.write(f"- Cache misses: {cache_stats['misses']}")
                
                # Create Excel writer object
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    # Write each DataFrame to a different worksheet
                    basic_df.to_excel(writer, sheet_name='Project List', index=False)
                    raw_df.to_excel(writer, sheet_name='RAW DATA', index=False)
                    financial_df.to_excel(writer, sheet_name='Financial Details', index=False)
                    technical_df.to_excel(writer, sheet_name='Technical Requirements', index=False)
                    
                    # Get workbook and worksheet objects
                    workbook = writer.book
                    
                    # Add formats
                    money_format = workbook.add_format({'num_format': '$#,##0.00'})
                    date_format = workbook.add_format({'num_format': 'mm/dd/yyyy'})
                    header_format = workbook.add_format({
                        'bold': True,
                        'bg_color': '#D3D3D3',
                        'border': 1
                    })
                    
                    # Format Project List worksheet
                    worksheet = writer.sheets['Project List']
                    # Set column widths based on the image layout
                    column_widths = {
                        'Link': 8,
                        'DSA AppId': 15,
                        'PTN': 15,
                        'Project Name': 30,
                        'Project Scope': 40,
                        'Project Cert Type': 30,
                        'Address': 35,
                        'City': 20,
                        'ZIP': 10
                    }
                    
                    for idx, col in enumerate(basic_columns):
                        worksheet.set_column(idx, idx, column_widths[col])
                        worksheet.write(0, idx, col, header_format)
                    
                    # Format RAW DATA worksheet
                    worksheet = writer.sheets['RAW DATA']
                    for idx, col in enumerate(raw_df.columns):
                        if 'Date' in col:
                            worksheet.set_column(idx, idx, 12, date_format)
                        else:
                            worksheet.set_column(idx, idx, 20)
                        worksheet.write(0, idx, col, header_format)
                    worksheet.freeze_panes(1, 0)
                    
                    # Format Financial Details worksheet
                    worksheet = writer.sheets['Financial Details']
                    for idx, col in enumerate(financial_df.columns):
                        if 'Amount' in col or 'Cost' in col:
                            worksheet.set_column(idx, idx, 15, money_format)
                        elif 'Date' in col:
                            worksheet.set_column(idx, idx, 12, date_format)
                        else:
                            worksheet.set_column(idx, idx, 20)
                        worksheet.write(0, idx, col, header_format)
                    worksheet.freeze_panes(1, 0)
                    
                    # Format Technical Requirements worksheet
                    worksheet = writer.sheets['Technical Requirements']
                    for idx, col in enumerate(technical_df.columns):
                        worksheet.set_column(idx, idx, 20)
                        worksheet.write(0, idx, col, header_format)
                    worksheet.freeze_panes(1, 0)
                
                # Display results
                st.success(f"✅ Successfully scraped {len(projects)} projects!")
                
                # Offer Excel download
                st.download_button(
                    "📥 Download Excel Workbook",
                    output.getvalue(),
                    f"dsa_projects_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key='download-excel'
                )
                
                # Show preview tabs
                tab1, tab2, tab3, tab4 = st.tabs(["📋 Project List", "📝 RAW DATA", "💰 Financial Details", "🔧 Technical Requirements"])
                
                with tab1:
                    st.dataframe(basic_df, use_container_width=True)
                
                with tab2:
                    st.dataframe(raw_df, use_container_width=True)
                
                with tab3:
                    st.dataframe(financial_df, use_container_width=True)
                
                with tab4:
                    st.dataframe(technical_df, use_container_width=True)
                
                # Show statistics
                stats = scraper.get_stats()
                st.subheader("📊 Scraping Statistics")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Total Requests", stats['total_requests'])
                with col2:
                    st.metric("Successful Requests", stats['successful_requests'])
                with col3:
                    st.metric("Failed Requests", stats['failed_requests'])
                with col4:
                    st.metric("Total Time", str(stats['elapsed_time']))
            else:
                st.error("❌ No projects found. Please check the Client ID and try again.")
                
        except Exception as e:
            st.error(f"❌ Error during scraping: {str(e)}")
            logger.error(f"Scraping error: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main() 