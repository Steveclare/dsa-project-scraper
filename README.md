# DSA Project Scraper

A Streamlit application that scrapes project data from the DSA (Division of the State Architect) website and organizes it into an Excel workbook.

## Live Demo
Visit the live application at: [DSA Project Scraper](https://share.streamlit.io/yourusername/dsa-project-scraper/main/dsa_scraper.py)

## Features

- Scrapes project data from DSA website
- Organizes data into three Excel worksheets:
  1. Project List - Standard format with basic project information
  2. Financial Details - Cost information and dates for bid estimation
  3. Technical Requirements - Compliance and technical specifications
- User-friendly interface with progress tracking
- Configurable request delay to avoid rate limiting
- Optional proxy support
- Excel export with formatted columns and data

## Local Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/dsa-project-scraper.git
cd dsa-project-scraper
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

## Usage

### Running Locally
1. Run the Streamlit app:
```bash
streamlit run dsa_scraper.py
```

2. In the web interface:
   - Enter your Client ID (default: 36-67)
   - Adjust request delay if needed
   - Configure proxy settings if required
   - Click "Start Scraping"

3. Download the Excel workbook with the scraped data

### Using the Live Demo
1. Visit the [live demo](https://share.streamlit.io/yourusername/dsa-project-scraper/main/dsa_scraper.py)
2. Follow the same steps as running locally

## Data Structure

### Project List Tab
- Link
- DSA AppId
- PTN
- Project Name
- Project Scope
- Project Cert Type

### Financial Details Tab
- Cost information
- Important dates
- Project classification
- Location details

### Technical Requirements Tab
- Compliance information
- Safety requirements
- Special project attributes

## Deployment

This application is deployed using [Streamlit Cloud](https://share.streamlit.io/). To deploy your own instance:

1. Fork this repository
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Sign in with your GitHub account
4. Select this repository
5. Deploy with one click

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/) 