# 99 -- Staging triples are not part of the output (iter4: moved out of 03, since
# 03b reads the note too). Keep this file last.

DELETE WHERE { ?s <urn:scilex:staging#note> ?note } ;
# iter7: venue staging of the survey bundle (rml/survey-venues.rml.ttl, sparql/06-survey-venues.ru)
DELETE WHERE { ?s <urn:scilex:staging#venueName> ?name } ;
DELETE WHERE { ?s <urn:scilex:staging#venueIssn> ?issn } ;
# iter8: raw eventtitle staged on the conference series (rml, sparql/07)
DELETE WHERE { ?s <urn:scilex:staging#eventtitle> ?t }
