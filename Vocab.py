import os
import random
import time
import collections
import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as widgets
from tf.app import use
A = use('bhsa', hoist=globals(), silent=True)

class TrainVocab:
  
    def __init__(self, score_sheet='score.csv', time_threshold=14):
        
        self.score = score_sheet
        self.threshold = time_threshold
        
        #Creating score file if not existing
        if not os.path.isfile(self.score):
            pd.DataFrame(columns=['lex','node','time_score','time_stamp','rep']).to_csv(self.score, index=False)
        
        word_list = [w for w in F.otype.s('word')]
        language_list = [F.language.v(w) for w in F.otype.s('word')]
        POS_list = [F.sp.v(w) for w in F.otype.s('word')]
        stem_list = [F.vs.v(w) for w in F.otype.s('word')]
        tense_list = [F.vt.v(w) for w in F.otype.s('word')]
        rank_list = [F.rank_lex.v(w) for w in F.otype.s('word')]
            
        self.words_df = pd.DataFrame(list(zip(word_list, language_list, POS_list, stem_list, tense_list, rank_list)),
                              columns = ['lex','Language','POS','Stem','Tense','Rank'])
        
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
        
        def commonFiltering(language, POS, stem, tense, start_level, end_level):
            
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
                
        def languageEvent(change):
            commonFiltering(change.new, self.choosePOS.value, self.chooseStem.value, self.chooseTense.value, self.startLevel.value, self.endLevel.value)

        def POSEvent(change):
            commonFiltering(self.chooseLanguage.value, change.new, self.chooseStem.value, self.chooseTense.value, self.startLevel.value, self.endLevel.value)
            
        def stemEvent(change):
            commonFiltering(self.chooseLanguage.value, self.choosePOS.value, change.new, self.chooseTense.value, self.startLevel.value, self.endLevel.value)
            
        def tenseEvent(change):
            commonFiltering(self.chooseLanguage.value, self.choosePOS.value, self.chooseStem.value, change.new, self.startLevel.value, self.endLevel.value)
            
        def StartLevelEvent(change):
            commonFiltering(self.chooseLanguage.value, self.choosePOS.value, self.chooseStem.value, self.chooseTense.value, change.new, self.endLevel.value)
            
        def EndLevelEvent(change):
            commonFiltering(self.chooseLanguage.value, self.choosePOS.value, self.chooseStem.value, self.chooseTense.value, self.startLevel.value, change.new)
        
        self.chooseLanguage.observe(languageEvent, names='value')
        self.startLevel.observe(StartLevelEvent, names='value')
        self.endLevel.observe(EndLevelEvent, names='value')
        self.choosePOS.observe(POSEvent, names='value')
        self.chooseStem.observe(stemEvent, names='value')
        self.chooseTense.observe(tenseEvent, names='value')
        
        box = widgets.HBox([self.startLevel, self.endLevel])
        tab_contents = ['Frequency','Part of Speech', 'Stem', 'Tense','Language']
        children = [box,self.choosePOS, self.chooseStem, self.chooseTense, self.chooseLanguage]
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
        word = random.choice(list(self.words.lex))
        
        if F.lex.v(word) in list(self.df.lex):
            level = self.getLevel(F.lex.v(word))
            
            if iteration > 200: #If iterations exeeded, select word with highest difficulty level
                self.df['level'] = self.df.apply(lambda x: self.getLevel(x['lex']), axis=1) #Calculating level for each lex
                highest_lex = self.df.sort_values(by='level', ascending=False)[:1].lex.item() #Choosing lex with highest level
                return random.choice([w for w in F.lex.s(highest_lex) if F.otype.v(w)=='word']) #Returning random word of given lex
                
            elif level > self.threshold: #If difficulty level threshold exceeded
                return word
            
            else:
                iteration+=1
                return self.GetWord(iteration)
        else:
            return word
        
    def Test(self):
        self.df = pd.read_csv(self.score)
        self.df.columns = ['lex','node','time_score','time_stamp','rep']
        old_data = pd.read_csv(self.score, index_col='lex')
        
        word = self.GetWord()
        A.plain(L.u(word, 'clause')[0], highlights = {word:'gold'})
        start_time = time.time()
        test = input("Gloss ")
        time_spent = time.time() - start_time
        
        if test == F.gloss.v(word):
            print('Correct!')
        else:
            print(f'Wrong. Correct answer is "{F.gloss.v(word)}"')
            if F.lex.v(word) not in list(old_data.index):
                start_time = time.time() - self.threshold*200000 #New but wrong entry is given more weight by predating entry
            else:
                start_time = old_data[old_data.index == F.lex.v(word)].time_stamp.item()
                time_spent = old_data[old_data.index == F.lex.v(word)].time_score.item()
            
        new_data = pd.DataFrame({F.lex.v(word):[word,time_spent, start_time, 1]}).T
        new_data.columns = ['node','time_score','time_stamp', 'rep']        
        
        if F.lex.v(word) in list(old_data.index):
            
            rep_score = old_data[old_data.index == F.lex.v(word)].rep.item()
            
            #Decreasing repetion score if more than 1 and correct answer.
            if rep_score > 1 and test == F.gloss.v(word):
                new_data.at[F.lex.v(word), 'rep'] = rep_score -1
            
            #Increasing repetition score if wrong answer
            elif test != F.gloss.v(word):
                new_data.at[F.lex.v(word), 'rep'] = rep_score +1
                
            old_data = old_data.drop(F.lex.v(word)) #Dropping existing row
            
        data = old_data.append(new_data)
        data = data.sort_index()
        data.index.name = 'lex'
        data.to_csv(self.score)
            
    def Stats(self):
        self.df = pd.read_csv(self.score)
        self.df.columns = ['lex','node','time_score','time_stamp','rep']
        
        pot_lexemes = set([F.lex.v(w) for w in list(self.words.lex)])
            
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