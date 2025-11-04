"""Constants for the Electric Ireland Insights integration."""

# Integration domain
DOMAIN = "electric_ireland_insights"

# Integration name
NAME = "Electric Ireland Insights"

# Number of days to look back when fetching historical data
# Electric Ireland publishes data with 1-3 days delay
LOOKUP_DAYS = 10

# Number of days to fetch in parallel for improved performance
PARALLEL_DAYS = 5
