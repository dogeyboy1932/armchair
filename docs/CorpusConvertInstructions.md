Claude_instructions
First Claude Academic Course:Topic
Definition Generation
Prompt and workflow used to generate definitions for syllabi topics for use in
curriculum mapping.
Each file was a text file with one topic per line structure like:
Course Name: Course Topic Covered
Specific examples might be:
Calculus III: Double Integrals Over General Regions
Modeling Human Physiology: Pulsatile Flow Model
Initial Prompt:
Could you please generate structured definitions for the
following items in the attached txt file? These are [DOMAIN]
related course names and topic phrases delimited by a semicolon
(:). I'd like to stick to 50-100 words, mentioning prerequisite
topic indexes if appropriate, Any cross-reference topic indexes
you see, and also any analogies that may be relevant to each
topic? If you could, please output as a json and include some
quality metrics as well.
Subsequent Prompts:
Excellent! Could you please do the same thing for the attached
[OTHER DOMAIN] topics, providing definitions, prereqs, and
cross-references? If possible, could you format the output as a
json again?
Cleanup Required
LLM Idiosyncrasies
For domains containing more than ~75 topics, the LLM usually needed
multiple rounds of processing, requiring the user to initiate continuation.
During this process, occasionally topics would be spliced together
incorrectly, partially overwritten, or topics may be introduced out-of-order,
requiring some editing of the completed artifact.
Text Formatting Issues
Certain characters output by the LLM are not available in all common font
packages. For example; certain math symbols ( ∲ ) and subscript letters ( ₙ ,
ₛ , ...) do not render with popular editing fonts like Consolas or Arial; but as
long as you work in UTF-8 encoding the characters should remain valid as a
part of the file. The LLM output of topics whose names included hyphens,
commas, or semicolons seemed to get chopped off and only keep the initial
text before the punctuation (e.g. "Non-Newtonian Fluids" → "Non"), so those
topics needed to be manually retyped/repaired. However, it appeared not to
affect the definitions, implying this was a "writing" not a "reading" issue.
Each domain began with index 0, which is important because the post-
processing scripts looked for an index of zero to calculate the offset required
to combine all domains into one, cohesive dataset. To ensure the LLM didn't
skip or add any topics, I took all the domain's topics and pasted them
together in a single file. I then manually merged the JSON outputs for all the
domains, read and extracted the course and topic titles, then wrote those
out to file to compare to the original. This way, I caught a few mistakes made
during the process like courses being accidentally added to multiple
domains or where two courses listed the same topic. Small errors were
corrected manually.
Final Processing
With each of the topics processed and JSON outputs merged, the final
processing involved re-indexing the topics, prerequisites, and cross-
references so that each topic had a unique index. This was done
programmatically. To generate vector embeddings to map and compare
topics, sentence transformers were used. The topic string was embedded as
its own vector, and the definition and analogy fields were concatenated and
embedded as a second vector. The final vector was a concatenation of the
<topic, definition+analogy> vectors.
Second Round Academic Mapping
Initial Prompt:
Attached is a list of academic topics [find in data/topic_definitions.json], with the name of the
course and the topic offered separated with a colon (:) on each
new line. Could you please provide the following for each course
topic in the file: 1. A concise definition that describes the
topic in the context of the course name (50-100 words). 2.
Please provide 3 to 5 analogies that might be useful in
explaining or describing the topic to students. 3. A short list
of prerequisite concepts that would be essential for students to
know before learning about this topic. Please format the output
as a JSON file to make it easy for me to parse.
Run with Claude Sonnet 4.5 - 11/3/2025
Lessons learned
With the enhanced output, the model absolutely cannot parse more than
about 60-65 topics. Instead of parsing out by course, just split all topics out
into lists of 40-50 topics for each run. Claude Sonnet 4.5 can crank out
around 300-400 until it hits the paid pro account usge limits.