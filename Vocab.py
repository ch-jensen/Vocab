import os
import random
import time
import collections
import pandas as pd
import matplotlib.pyplot as plt
from tf.app import use
A = use('bhsa', hoist=globals(), silent=True)

class TrainVocab:
    
    def __init__(self, language='Hebrew',score_sheet='score.csv', proper_names=True,
                 start_level=0, end_level=100, time_threshold=14):
        self.language = language
        self.proper_names = proper_names
        self.score = score_sheet
        self.start_level = start_level
        self.end_level = end_level
        self.threshold = time_threshold
        
        #Select all words below freq level
        self.word_list = [w for w in F.otype.s('word') if F.rank_lex.v(w) >= start_level and F.rank_lex.v(w) <= end_level]
        
        #Proper names and language constraint
        if not self.proper_names:
            self.word_list = [w for w in self.word_list if F.language.v(w) == self.language and F.sp.v(w) != 'nmpr']
        else: 
            self.word_list = [w for w in self.word_list if F.language.v(w) == self.language]

        #Creating score file if not existing
        if not os.path.isfile(self.score):
            pd.DataFrame(columns=['node','time_score','time_stamp','rep']).to_csv(self.score, index=False)
        
    def getLevel(self, lex):
        mean_score = self.df.time_score.mean()
        elapsed_time = time.time() - self.df[self.df.lex == lex].time_stamp.item()
        time_score = self.df[self.df.lex == lex].time_score.item()
        repetitions = self.df[self.df.lex == lex].rep.item()
        return elapsed_time * time_score * repetitions / mean_score / 86400 #seconds per day
        
    def GetWord(self, iteration=0):
        word = random.choice(self.word_list)

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
    
    def Visualize(self, word):
        A.plain(L.u(word, 'clause')[0], highlights = {word:'gold'})
        
    def Test(self):
        self.df = pd.read_csv(self.score)
        self.df.columns = ['lex','node','time_score','time_stamp','rep']
        old_data = pd.read_csv(self.score, index_col='Unnamed: 0')
        
        word = self.GetWord()
        self.Visualize(word=word)
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
        data.to_csv(self.score)
            
    def Stats(self):
        self.df = pd.read_csv(self.score)
        self.df.columns = ['lex','node','time_score','time_stamp','rep']
        pot_lexemes = set([F.lex.v(w) for w in self.word_list])
        
        #Get active lexemes, that is, all lexemes below learning threshold
        self.df['level'] = self.df.apply(lambda x: self.getLevel(x['lex']), axis=1)
        active_lexemes = self.df[(self.df.lex.isin(pot_lexemes)) & (self.df.level < self.threshold)]
        fraction = len(active_lexemes)/len(pot_lexemes)*100
        
        plt.pie([fraction, 100-fraction])
        plt.title(f'{round(fraction, 2)}% active at level {self.start_level}-{self.end_level}')
        plt.show()