Processing Pipeline for Syllabus Topic Map
1. Clean syllabi and convert to JSON
Manually go through each syllabus and extract the topics covered,
separating each topic into its own entry. the template expected will look like
this:
{
"domain": "MechSE",
"abbr": "me",
"year": 2025,
"sources": [],
"courses": [
{"id": "CHEM 102",
"name": "General Chemistry I",
"credits": 3,
"textbooks": ["Chemistry: An Atoms First Approach,
3rd edition, by Zumdahl, Zumdahl & DeCoste."],
"description": "For students who have some prior
knowledge of chemistry. Principles governing atomic
structure, bonding, states of matter, stoichiometry, and
chemical equilibrium.",
"designation": {
"ME": "core",
"EM": "core"
},
"prereq": {
"type": "SIMPLE",
"courses": ["MATH 112"]
},
"coprereq": {
"type": "SIMPLE",
"courses": ["CHEM 103"]
},
where the ... indicates additional entries as needed. Note the prereq and
coreq structure. Types allowed are:
You can chain conditions together using the "conditions" keyword instead of
"courses" which tells the parser to prepare for unpacking. That looks like this
(example used is MATH 257):
"objectives": ["By the end of this course, students
will have developed a strong foundation and demonstrate
understanding in essential chemical knowledge in atomic
structure, chemical bonding, chemical stoichiometry, and
chemical equilibrium. Students will also be able to solve
problems related to chemical concepts, as well as those not
previously seen. Students will have learned about the
contribution of diverse range of people to the scientific
development of the course topics, including scholarship of
women and gender in chemistry."],
"topics": ["Dalton's Atomic Theory",
...
],
"definitions": [
{ "d_source": [],
"d_term": [],
"d_entry": []
}]
},
...
]
}
SIMPLE - list containing a single course
NONE - No prereq/coreq
AND - list containing multiple courses
OR - list containing multiple courses
The above example would be interpreted as: Prerequisites include CS 101
and one of MATH 220 or MATH 221. Again, all this should be manually
entered. Typically takes around 5-10 minutes per syllabus once you get the
hang of it. A full list of rules I used when parsing syllabi can be found in
syllabus_processing_rules.md .
2. Split topic lists into groups of 50
Read through all topics from all courses, and take the course name ("name")
and concatenate the topic ("topics"). The first four topics from CHEM 102
look like this:
Split the total list covering all courses into text files with one course:topic
entry per line with at most 50 entries per file. From testing in 2025/2026, full
models of Claude had a memory limit that would get overwhelmed if you try
for more than this in one shot.
"prereq": {
"type": "AND",
"conditions": [
{
"type": "SIMPLE",
"courses": ["CS 101"]
},
{
"type": "OR",
"courses": ["MATH 220", "MATH 221"]
}
]
},
General Chemistry I: Dalton's atomic theory
General Chemistry I: Intro to electromagnetic radiation
General Chemistry I: Photoelectric affect
General Chemistry I: The hydrogen atom
3. Prompt LLM to generate contextual definitions
The team did not provide any funds or accounts for LLMs, so I ended up
using my own personal account for the project. I configured ClaudeCode
with Claude 4.5 Sonnet to have access to a directory on my machine with
only the cleaned lists of 50 course:topic items, and fed it an initial prompt to
process the files one at a time, by name, ensuring that the resulting
definitions were saved to JSON files back on my system. I was able to
process around 300-400 topics (8-10 files) per day with a Pro account and
not using any other tokens. The whole process took me 3-4 days to
complete for a curriculum with 50-70 courses. A summary detailing the
history of prompts and troubleshooting can be found in
Claude_instructions.md . I had the LLM generate a brief definition, 3-5
analogies, and prerequisites. I post-processed the files to add the course
"id" (e.g. CHEM 102) into each entry to make it easier to index by course ID
rather than full name. I stand by this decision to not include the ID in the
LLM task to avoid it rearranging things based on guesses about the ID
numbers.
4. Reassemble defined topics into flat file
Manually combine back the separate outputs to a single JSON file. Use a
web-based JSON validator to save yourself the headache of trying to find a
missing bracket or comma. The combined JSON should now look like this:
[
{
"course": "General Chemistry I",
"topic": "Dalton's atomic theory",
"definition": "Dalton's atomic theory proposes that all
matter is composed of indivisible atoms, which are the
fundamental building blocks of elements. Each element
consists of identical atoms with characteristic mass, while
atoms of different elements differ in mass and properties.
Chemical reactions involve the rearrangement of atoms, not
5. Run script build_shell_features.py
It will take in a sentence_transformers modelname (we used
"malteos/scincl" ), the combined, clean JSON containing the LLM
outputs, and you'll want to adjust the output filenames as well.
There are extra features in the script which are no longer used, and are
there from legacy attempts at the model which were deemed to be not the
direction the team wanted to go. You can clean them out if you like. I kept
their creation or destruction, and compounds form when atoms
combine in simple whole-number ratios.",
"analogies": [
"Atoms are like LEGO bricks - they're the smallest
building blocks that combine in specific ways to create
different structures, but the bricks themselves remain
unchanged.",
"Think of atoms as letters in an alphabet - each
element is a different letter, and compounds are words formed
by combining these letters in specific patterns.",
"Atoms are like indestructible marbles of different
colors and weights - they can be rearranged into different
groups, but you can't create or destroy individual marbles.",
"Elements are like families where all members (atoms)
share identical traits, while different families have
distinct characteristics."
],
"prerequisites": [
"Basic understanding of matter and substances",
"Concept of elements and compounds",
"Law of conservation of mass"
],
"id": "CHEM 102"
},
...
]
them there in case the team suddenly decided they wanted to revert or
change the focus of the project.
6. Run script generate_web_connections.py
After the output is generated from step 5, this script takes in the graph
structure (graphml file) and the topiclist data structure (list of Topics) and
does two things:
- It will apply a weighted score to the vector features of the LLM generated
components to score the similarity between items and pull the topK results
to save to JSON output
- It will format and output a graphml file for viewing in Gephi. I later used the
SigmaExporter plugin to generate the graph view of the model, and edited
the JS and HTML files to achieve the search and filtering.
Conclusion
That's where we left the project. The team asked to pivot to math notation
and extracting topics from course materials later, and the file repo has my
notes from investigating those approaches, but the PI's indicated they were
more inclined to manual curation of an initial list to start from, so we didn't
get very far into that approach. The above approach could obviously be
extended or refined to produce a different result; for example, you could ask
the LLM to generate a different set of features to encode and compare. You
could also change the weighting for calculating the topK matches.