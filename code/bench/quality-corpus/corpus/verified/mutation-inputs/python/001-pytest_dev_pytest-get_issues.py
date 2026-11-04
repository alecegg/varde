def get_issues():
    issues = []
    url = issues_url
    while 1:
        get_data = {"state": "all"}
        r = requests.get(url, params=get_data)
        data = r.json()
        if r.status_code == 403:
            # API request limit exceeded
            print(data["message"])
            sys.exit(1)
        issues.extend(data)

        # Look for next page
        links = requests.utils.parse_header_links(r.headers["Link"])
        another_page = False
        for link in links:
            if link["rel"] == "next":
                url = link["url"]
                another_page = True
        if not another_page:
            return issues
