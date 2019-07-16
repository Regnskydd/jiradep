#!/usr/bin/env python3

def die(message):
    print(message)
    import sys
    sys.exit(1)

import optparse
import json
import getpass

try:
    import pygraphviz as pgv
except ImportError:
    die("Please install pygraphviz (in debian: python3-pygraphviz)")
try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    die("Please install restkit (in debian: python3-requests)")

def fetcher_factory(server_url, auth):
    """ This factory will create the actual method used to fetch issues from JIRA. This is really just a closure that saves us having
        to pass a bunch of parameters all over the place all the time. """
    def get_issue(key):
        """ Given an issue key (i.e. DEMO-1) return the JSON representation of it. """
        print('Fetching ' + key)

        request_url = server_url + "/rest/agile/1.0/issue/" + key
        response = requests.get(url=request_url,auth=auth,headers={"Accept": "application/json"})
        
        if response.status_code == 200:
            #print(json.dumps(json.loads(response.text), indent=4, sort_keys=True))
            return json.loads(response.text)
        else:
            return None
    return get_issue
    
def add_dependencies_to_graph(graph, get_issue):
    """ Given a starting issue key and the issue-fetching function build up the GraphViz data representing relationships
        between issues. This will consider both subtasks and issue links.
    """
    def get_key(issue):
        return issue['key']

    # since the graph can be cyclic we need to prevent infinite recursion
    seen = []

    def walk(issue_key, graph):
        """ issue is the JSON representation of the issue """
        try:
            issue = get_issue(issue_key)
        except Exception:
            print("Could not get issue:", issue_key)
            raise()
        
        seen.append(issue_key)
        children = []

        # Add each linked issue we can find to the graph
        for link in issue['fields']['issuelinks']:
            if 'outwardIssue' in link:
                if (get_key(issue), get_key(link['outwardIssue'])) not in graph.edges():
                    graph.add_node(get_key(link['outwardIssue']), style='filled', label=get_key(link['outwardIssue']) + "\n" + link['outwardIssue']['fields']['summary'], penwidth='2.0')
                    graph.add_edge(get_key(issue), get_key(link['outwardIssue']), label=link['type']['outward'])
                    children.append(get_key(link['outwardIssue']))
            if 'inwardIssue' in link:
                if (get_key(link['inwardIssue']), get_key(issue)) not in graph.edges():
                    graph.add_node(get_key(link['inwardIssue']), style='filled', label=get_key(link['inwardIssue']) + "\n" + link['inwardIssue']['fields']['summary'], penwidth='2.0')
                    graph.add_edge(get_key(link['inwardIssue']), get_key(issue), label=link['type']['outward'])
                    children.append(get_key(link['inwardIssue']))
        # now construct graph data for all links of this issue
        for child in (x for x in children if x not in seen):
            walk(child, graph)
        return graph

    # Starting building the graph recursively with the first element in out graph
    graph = walk(graph.nodes()[0], graph)
    return graph

# Since it doesn't appear to be possible to determine the type of an issue based on the metadata, we utilizes the API to attempt to fetch an epic.
# If it returns 200, it is an epic and the shape should be updated, if it returns 40X it is not an epic and we will leave it be.
# https://developer.atlassian.com/cloud/jira/software/rest/#api-rest-agile-1-0-epic-epicIdOrKey-get
def update_shape_on_epics(graph, server_url, auth):
    for node in graph:
        request_url = server_url + "/rest/agile/1.0/epic/" + node
        response = requests.get(url=request_url,auth=auth,headers={"Accept": "application/json"})
        if response.status_code == 200:
            node.attr['shape'] = 'folder'
    return graph

# Returns all issues that belong to the epic, for the given epic ID.
# https://developer.atlassian.com/cloud/jira/software/rest/#api-rest-agile-1-0-epic-epicIdOrKey-post
def get_issues_in_epic(server_url, epic_key, auth):
    request_url = server_url + "/rest/agile/1.0/epic/" + epic_key + "/issue"
    response = requests.get(url=request_url,auth=auth,headers={"Accept": "application/json"})
    #print(json.dumps(json.loads(response.text), sort_keys=True, indent=4, separators=(",", ": ")))
    if response.status_code == 200:
        return json.loads(response.text)
    else:
        return None 

# Adds all issues belonging in an epic to the graph
def add_issues_to_graph(graph, epic, epic_key):
    for issue in epic["issues"]:
        if(issue["key"]) not in graph.edges():
            graph.add_node(issue["key"], style='filled', penwidth='2.0')         
            graph.add_edge(epic_key, issue["key"], color='blue', penwidth='0.5')
            #print(json.dumps(json.loads(issue), sort_keys=True, indent=4, separators=(",", ": ")))
    return graph

# Returns a specific color based on the status of the issue
def update_graph_with_issue_progress(graph, get_issue):
    for node in graph:
        """ issue is the JSON representation of the issue """
        try:
            issue = get_issue(node)
        except Exception:
            print("Could not get issue:", node)
            raise()
      
        if issue["fields"]["status"]["name"] == "To Do":
            node.attr['fillcolor'] = 'white'
        elif issue["fields"]["status"]["name"] == "In Progress":
            node.attr['fillcolor'] = 'yellow'
        elif issue["fields"]["status"]["name"] == "Done":
            node.attr['fillcolor'] = 'green'
                    
    return graph

def create_graph_image(graph, image_file):
    graph.layout(prog='dot')
    print('Writing to ' + image_file)
    graph.draw(image_file)

def parse_args():
    parser = optparse.OptionParser()
    parser.add_option('-u', '--user', dest='user', default=getpass.getuser(), help='Username to access JIRA')
    parser.add_option('-p', '--password', dest='password', help='Password to access JIRA')
    parser.add_option('-j', '--jira', dest='jira_url', default='http://localhost:8080', help='JIRA Base URL')
    parser.add_option('-f', '--file', dest='image_file', default='issue_graph.png', help='Filename to write image to')
    parser.add_option('-v', '--verbose', dest='verbose', default=False, help='Adds all tasks that belongs to starting epic to graph')
    
    return parser.parse_args()

def get_password():
    return getpass("Please enter the Jira Password:")

if __name__ == '__main__':
    (options, args) = parse_args()
 
    # Basic Auth is usually easier for scripts like this to deal with than Cookies.
    auth = HTTPBasicAuth(options.user, options.password or get_password())
    issue_fetcher = fetcher_factory(options.jira_url, auth)

    if len(args) != 1:
        die('Must specify exactly one issue key. (e.g. DEMO-1)')
    start_issue_key = args[0]

    # Create graph containing starting epic
    graph = pgv.AGraph(strict=False, directed=True)
    graph.graph_attr['label'] = 'Dependency Graph for %s' % start_issue_key
    graph.add_node(start_issue_key, style='filled', shape='folder', penwidth='2.0')
 
    # Get all dependencies to the graph
    graph = add_dependencies_to_graph(graph, issue_fetcher)

    # Since an issue could be linked to an EPIC (instead of belonging to) we want to distinguish does.
    graph = update_shape_on_epics(graph, options.jira_url, auth)

    # Check if full issue tree shall be added to graph
    if options.verbose == True:
        epic = get_issues_in_epic(options.jira_url, start_issue_key, auth)
        graph = add_issues_to_graph(graph,epic,start_issue_key)

    # Check the status of each issue and update the color depending on the status
    graph = update_graph_with_issue_progress(graph, issue_fetcher)
        
    # Create a picture from graph
    create_graph_image(graph, options.image_file)

    # TODO
    # Add support for summary in input epic
    # Add verbose for all epics not only starting epic
    # Add support for subgraphs to make the output abit clearer when using --verbose.
    # Add support for keys so jenkins can use it?

    # Funderingar, hur gör man detta snyggt egentligen? Känns som man får slänga med massor inloggningsuppgifter och URL överallt för att kunna hämta ärenden i varje funktion.
    
