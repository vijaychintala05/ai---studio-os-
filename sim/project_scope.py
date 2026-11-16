"""Read-only checks against each public endpoint's project-reference contract."""
def out_of_scope(path,row,projects):
    if path == '/api/site-reports':
        # This legacy response exposes the name, not project_id. Require a
        # nonempty exact visible name; never treat an absent reference as safe.
        return not row.get('project') or row['project'] not in projects.values()
    return row.get('project_id') not in projects
