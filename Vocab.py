import os, re
from os import listdir
import random
import time
import collections
import statistics
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, HTML
import ipywidgets as widgets
from tf.app import use
A = use('etcbc/bhsa', hoist=globals(), silent=True)

class TrainVocab:
  
    def __init__(self, time_threshold=2):
        
        self.threshold = time_threshold
        gloss_files = [f for f in listdir() if '_glosses.csv' in f]
        gloss_languages = [f.rstrip('_glosses.csv') for f in gloss_files]
        gloss_languages.append('English')
        self.lex = ''
        
        self.score = f'English_score.csv'
        #Creating score file if not existing
        if not os.path.isfile(self.score):
            pd.DataFrame(columns=['lex','node','time_score','time_stamp','rep']).to_csv(self.score, index=False)
        
        word_list = [w for w in F.otype.s('word')]
        lex_list = [F.lex.v(w) for w in F.otype.s('word')]
        language_list = [F.language.v(w) for w in F.otype.s('word')]
        POS_list = [F.sp.v(w) for w in F.otype.s('word')]
        stem_list = [F.vs.v(w) for w in F.otype.s('word')]
        tense_list = [F.vt.v(w) for w in F.otype.s('word')]
        rank_list = [F.rank_lex.v(w) for w in F.otype.s('word')]
            
        self.words_df = pd.DataFrame(list(zip(word_list, lex_list, language_list, POS_list, stem_list, tense_list, rank_list)),
                              columns = ['word','lex','Language','POS','Stem','Tense','Rank'])
        
        stems = [s[0] for s in F.vs.freqList() if s[0] not in {'NA','N/A','absent'}]
        
        mapTense = {'qatal': 'perf',
           'yiqtol': 'impf',
          'wayyiqtol': 'wayq',
          'active particple': 'ptca',
          'infinitive construct': 'infc',
          'imperative': 'impv',
          'passive participle': 'ptcp',
          'infinitive absolute': 'infa'}
        
        mapPOS = {'noun': 'subs',
          'verb': 'verb',
          'preposition': 'prep',
          'conjunction': 'conj',
          'proper noun': 'nmpr',
          'article': 'art',
          'adjective': 'adjv',
          'negative': 'nega',
          'personal pronoun': 'prps',
           'adverb': 'advb',
          'demonstrative pronoun': 'prde',
          'interjection': 'intj',
          'interrogative particle': 'inrg',
          'interrogative pronoun': 'prin'}
        
        self.choosePOS =  widgets.SelectMultiple(
            options= list(mapPOS.keys()),
            value = list(mapPOS.keys()),
            description='Part of Speech',
            )
        
        self.chooseStem = widgets.SelectMultiple(
            options=stems,
            value=stems,
            description='Stem',
            )
        
        self.chooseTense =  widgets.SelectMultiple(
            options=list(mapTense.keys()),
            value=list(mapTense.keys()),
            description='Tense',
            )
        
        self.startLevel = widgets.BoundedIntText(
            value=0,
            min=0,
            max=5713,
            step=1,
            description='Start level:',
        )

        self.endLevel = widgets.BoundedIntText(
            value=100,
            min=0,
            max=5713,
            step=1,
            description='End level:',
        )
        
        self.chooseLanguage =  widgets.SelectMultiple(
            options= ['Hebrew','Aramaic'],
            value = ['Hebrew'],
            description='Language',
            )
        
        self.chooseGlosses =  widgets.SelectMultiple(
            options= gloss_languages,
            value = ['English'],
            description='Language',
            )
        
        def commonFiltering(glosses, language, POS, stem, tense, start_level, end_level):
            
            POS = [mapPOS[w] for w in POS]
            stem = list(stem)
            tense = [mapTense[w] for w in tense]
            
            if 'verb' in POS:
                stem.append('NA')
                tense.append('NA')
                
                self.words = self.words_df[(self.words_df.Language.isin(list(language)))&
                            (self.words_df.POS.isin(POS)) &
                            (self.words_df.Stem.isin(stem)) &
                            (self.words_df.Tense.isin(tense)) &
                            (self.words_df.Rank >= start_level) &
                            (self.words_df.Rank <= end_level)]
            else:
                self.words = self.words_df[(self.words_df.Language.isin(list(language))) &
                            (self.words_df.POS.isin(POS)) &
                            (self.words_df.Rank >= start_level) &
                            (self.words_df.Rank <= end_level)]
                
            self.score = f'{glosses[0]}_score.csv'
            #Creating score file if not existing
            if not os.path.isfile(self.score):
                pd.DataFrame(columns=['lex','node','time_score','time_stamp','rep']).to_csv(self.score, index=False)
            if glosses[0] != 'English':
                self.gloss_list = pd.read_csv(f'{self.chooseGlosses.value[0]}_glosses.csv', index_col = 'Unnamed: 0')
                existing_glosses = list(self.gloss_list.dropna(subset=list(self.gloss_list.columns[1:]), how='all').lex)
                self.words = self.words[self.words.lex.isin(existing_glosses)]
        
        def glossEvent(change):
            commonFiltering(change.new, self.chooseLanguage.value, self.choosePOS.value, self.chooseStem.value, self.chooseTense.value, self.startLevel.value, self.endLevel.value)
                
        def languageEvent(change):
            commonFiltering(self.chooseGlosses.value, change.new, self.choosePOS.value, self.chooseStem.value, self.chooseTense.value, self.startLevel.value, self.endLevel.value)

        def POSEvent(change):
            commonFiltering(self.chooseGlosses.value, self.chooseLanguage.value, change.new, self.chooseStem.value, self.chooseTense.value, self.startLevel.value, self.endLevel.value)
            
        def stemEvent(change):
            commonFiltering(self.chooseGlosses.value, self.chooseLanguage.value, self.choosePOS.value, change.new, self.chooseTense.value, self.startLevel.value, self.endLevel.value)
            
        def tenseEvent(change):
            commonFiltering(self.chooseGlosses.value, self.chooseLanguage.value, self.choosePOS.value, self.chooseStem.value, change.new, self.startLevel.value, self.endLevel.value)
            
        def StartLevelEvent(change):
            commonFiltering(self.chooseGlosses.value, self.chooseLanguage.value, self.choosePOS.value, self.chooseStem.value, self.chooseTense.value, change.new, self.endLevel.value)
            
        def EndLevelEvent(change):
            commonFiltering(self.chooseGlosses.value, self.chooseLanguage.value, self.choosePOS.value, self.chooseStem.value, self.chooseTense.value, self.startLevel.value, change.new)
        
        self.chooseLanguage.observe(languageEvent, names='value')
        self.startLevel.observe(StartLevelEvent, names='value')
        self.endLevel.observe(EndLevelEvent, names='value')
        self.choosePOS.observe(POSEvent, names='value')
        self.chooseStem.observe(stemEvent, names='value')
        self.chooseTense.observe(tenseEvent, names='value')
        self.chooseGlosses.observe(glossEvent, names='value')
        
        box = widgets.HBox([self.startLevel, self.endLevel])
        tab_contents = ['Frequency','Part of Speech', 'Stem', 'Tense','Language', 'Gloss language']
        children = [box,self.choosePOS, self.chooseStem, self.chooseTense, self.chooseLanguage, self.chooseGlosses]
        tab = widgets.Tab()
        tab.children = children
        for i in range(len(tab_contents)):
            tab.set_title(i, tab_contents[i])
        display(tab)
        
        try:
            self.words
        except:
            self.words = self.words_df[(self.words_df.Language == 'Hebrew') &
                                        (self.words_df.Rank >= self.startLevel.value) & 
                                      (self.words_df.Rank <= self.endLevel.value)]
         
    def getLevel(self, lex):
        mean_score = self.df.time_score.mean()
        elapsed_time = time.time() - self.df[self.df.lex == lex].time_stamp.item()
        time_score = self.df[self.df.lex == lex].time_score.item()
        repetitions = self.df[self.df.lex == lex].rep.item()
        return elapsed_time * time_score * repetitions / mean_score / 86400 #seconds per day
        
    def GetWord(self, iteration=0):
        word = random.choice(list(self.words.word))
        
        if F.lex.v(word) in list(self.df.lex):
            level = self.getLevel(F.lex.v(word))
            
            if iteration > 50: #If iterations exeeded, select word with highest difficulty level
                self.df['level'] = self.df.apply(lambda x: self.getLevel(x['lex']), axis=1) #Calculating level for each lex
                highest_lex = random.choice(list(self.df.sort_values(by='level', ascending=False)[:10].lex)) #Choosing random lexeme among highest level lexemes
                return random.choice([w for w in F.lex.s(highest_lex) if F.otype.v(w)=='word']) #Returning random word of given lex

            elif F.lex.v(word) == self.lex:
                iteration+=1
                return self.GetWord(iteration)
                
            elif level > self.threshold: #If difficulty level threshold exceeded
                return word
            
            else:
                iteration+=1
                return self.GetWord(iteration)
        else:
            return word
        
    def lexFact(self):

        stem_dict = collections.defaultdict(lambda: collections.defaultdict(int))
        example_dict = collections.defaultdict(lambda: collections.defaultdict())

        lex = F.lex_utf8.v(self.word)
        
        display(HTML(f"<h3 style=font-family:Times align=left>{lex}</>"))
        display(HTML("freq. rank: {}\n".format(F.rank_lex.v(self.word))))
        
        if F.sp.v(self.word) == 'verb':
            for w in F.lex.s(F.lex.v(self.word))[1:]:
                stem_dict[lex][F.vs.v(w)] += 1
                if F.prs.v(w) == 'absent':
                    example_dict[lex][F.vs.v(w)] = w
                    
            for lex in stem_dict:
                for st in stem_dict[lex]:
                    display(HTML("{}: {} attestations".format(st, stem_dict[lex][st])))

                    if st in example_dict[lex]:
                        A.pretty(example_dict[lex][st])
        
    def Test(self):
        self.df = pd.read_csv(self.score)
        self.df.columns = ['lex','node','time_score','time_stamp','rep']
        old_data = pd.read_csv(self.score, index_col='lex')
        
        self.word = self.GetWord()
        self.lex = F.lex.v(self.word)
        
        if self.chooseGlosses.value[0] == 'English':
            gloss = F.gloss.v(self.word)
        else:
            if F.vs.v(self.word) != 'NA':
                if self.gloss_list[self.gloss_list.lex == F.lex.v(self.word)][F.vs.v(self.word)].any():
                    gloss = self.gloss_list[self.gloss_list.lex == F.lex.v(self.word)][F.vs.v(self.word)].item()
                else:
                    lex_df = self.gloss_list[self_gloss_list.lex == F.lex.v(self.word)]
                    for st in lex_df.columns[1:]:
                        if lex_df[st].any():
                            gloss = (lex_df[st].item())
                            break
            else:
                gloss = self.gloss_list[self.gloss_list.lex == F.lex.v(self.word)].default.item()
        
        gloss = re.split('; |, ', gloss)
        
        A.plain(L.u(self.word, 'clause')[0], highlights = {self.word:'gold'})
        start_time = time.time()
        test = input("Gloss ")
        time_spent = time.time() - start_time
        
        if test in [re.sub('\([a-z]*\)', '', w).rstrip() for w in gloss]: #Removing parentheses with content, e.g. "how (interr)" > "how"
            display(HTML('<p  style="color: green;">Correct!'))
            other_glosses = [g for g in gloss if g != test]
            if other_glosses:
                print(f'Other possible answers are "{", ".join(other_glosses)}"')
            
        else: #Wrong answer
            display(HTML('<p  style="color: red;">Wrong.'))
            print(f'Correct answer is "{", ".join(gloss)}"')
            start_time = time.time() - self.threshold*200000 #Wrong answer is given more weight by predating entry
                
        self.lexFact()
            
        new_data = pd.DataFrame({F.lex.v(self.word):[self.word,time_spent, start_time, 1]}).T
        new_data.columns = ['node','time_score','time_stamp', 'rep']        
        
        if F.lex.v(self.word) in list(old_data.index):
            
            rep_score = old_data[old_data.index == F.lex.v(self.word)].rep.item()
            
            #Decreasing repetion score if more than 1 and correct answer.
            if rep_score > 1 and test in gloss:
                new_data.at[F.lex.v(self.word), 'rep'] = rep_score -1
            
            #Increasing repetition score if wrong answer
            elif test not in gloss:
                new_data.at[F.lex.v(self.word), 'rep'] = rep_score +1
                
            old_data = old_data.drop(F.lex.v(self.word)) #Dropping existing row
        if len(old_data)>0:
            data = pd.concat([old_data, new_data])
        else:
            data = new_data
        data = data.sort_index()
        data.index.name = 'lex'
        data.to_csv(self.score)
            
    def Stats(self):
        self.df = pd.read_csv(self.score)
        self.df.columns = ['lex','node','time_score','time_stamp','rep']

        pot_lexemes = set([F.lex.v(w) for w in list(self.words.word)])
            
        #Get active lexemes, that is, all lexemes below learning threshold
        if len(self.df) > 0:
            self.df['level'] = self.df.apply(lambda x: self.getLevel(x['lex']), axis=1)
            active_lexemes = self.df[(self.df.lex.isin(pot_lexemes)) & (self.df.level < self.threshold)]
        else:
            active_lexemes = []
        
        fraction = len(active_lexemes)/len(pot_lexemes)*100
        
        plt.pie([fraction, 100-fraction])
        plt.title(f'{round(fraction, 2)}% active at level {self.startLevel.value}-{self.endLevel.value}')
        plt.show()

        if len(active_lexemes) > 0:
             print(f'Average time: {round(statistics.mean(active_lexemes.time_score),3)}')
        print(f"Presets: {', '.join([w for w in self.choosePOS.value])}, {', '.join([w for w in self.chooseStem.value])}, {', '.join([w for w in self.chooseTense.value])}")
        