from sim.project_scope import out_of_scope


def test_site_report_name_is_checked_against_visible_project_names():
    assert not out_of_scope('/api/site-reports',{'project':'Fictional Site A'},{11:'Fictional Site A'})


def test_hidden_and_missing_site_reference_are_refused():
    for row in ({'project':'Fictional Site B'},{}, {'project':None}):
        assert out_of_scope('/api/site-reports',row,{11:'Fictional Site A'})


def test_id_based_endpoints_keep_requiring_visible_project_id():
    for path in ('/api/tasks','/api/documents'):
        assert not out_of_scope(path,{'project_id':11},{11:'Fictional Site A'})
        assert out_of_scope(path,{'project_id':12},{11:'Fictional Site A'})
        assert out_of_scope(path,{}, {11:'Fictional Site A'})
