# Vocab

This is a training program for practicing Biblical vocabulary (Hebrew and Aramaic). As any language learner will know, vocabulary practicing is an almost endless endeavor. It is the assumption of this program that there is hardly any such thing as “knowing” a lexeme. Rather, a lexeme is either cognitively active or inactive. An active lexeme is defined here as a lexeme that has been practiced relatively recently, with a short response time, and with a low record of mistaken responses. By contrast, an inactive lexeme was practiced relatively long time ago, with a long response time, and/or with a high record of mistaken responses. This program essentially applies an algorithm that aims to yield those words which are the most difficult for you and let you practice those instead of those already active in your vocabulary. Another feature of this program is that you are not practicing dictionary forms of the lexemes but those forms that actually exist in the Hebrew Bible. In doing so, you should be well-equipped for reading the real text.

<img src="images/Vocab%20training.png">

## Updates

Dec. 21 2020: First commit and first version. A simple tool to excercise Biblical Hebrew with English glosses along with an algorithm to keep track of the learning and identify lexemes to practice.

Feb. 11 2022: 2nd version. A major update to allow excersing Biblical Hebrew with own lists of glosses other than the standard English glosses of the database. In addition, an interactive ipython widget was introduced to allow setting the properties for the lexemes to learn (e.g., verbal stem, tense).

## Get started

```pip install text-fabric```

```pip install jupyter```

```pip install ipywidgets```

To run the program, you need to download and store the following files in the same folder:
* Vocabulary training.ipynb
* Vocab.py
* Danish_glosses.csv
