from . import linkedin, stepstone, indeed

SCRAPERS = {
    "linkedin": linkedin.scrape,
    "stepstone": stepstone.scrape,
    "indeed": indeed.scrape,
}
