# AUTOGENERATED! DO NOT EDIT! File to edit: notebooks/Searching RSS feeds with haystack.ipynb (unless otherwise specified).

__all__ = ['Searcher']

# Cell
import pprint
import numpy as np
import pandas as pd
import requests
import torch
from sklearn import metrics
from nltk import tokenize
from operator import itemgetter

from haystack.database.elasticsearch import ElasticsearchDocumentStore
from haystack.database.memory import InMemoryDocumentStore

from haystack.retriever.dense import EmbeddingRetriever
from pytorch_hackathon import rss_feeds

import seaborn as sns

# Cell



class Searcher:

    def __init__(
        self,
        model_name,
        text_col,
        use_gpu,
        max_document_length=256,
        quantize_model=True,
        document_store_cls=InMemoryDocumentStore
    ):
        self.text_col = text_col
        self.embedding_col = text_col + '_emb'
        self.max_document_length = max_document_length
        self.model_name = model_name
        self.document_store = document_store_cls(
            embedding_field=self.embedding_col,
        )
        self.retriever = self._setup_retriever(use_gpu, quantize_model)

    def _setup_retriever(self, use_gpu, quantize_model):
        retriever = EmbeddingRetriever(
            document_store=self.document_store,
            embedding_model=self.model_name,
            use_gpu=use_gpu)
        if not use_gpu and quantize_model:
            self.set_quantized_model(retriever)

        return retriever

    def add_texts(
        self,
        df
    ):
        truncated_texts = [
            ' '.join(tokenize.wordpunct_tokenize(text)[:self.max_document_length])
            for text in df[self.text_col]
        ]
        article_embeddings = self.retriever.embed_queries(
            texts=truncated_texts
        )

        df[self.embedding_col] = article_embeddings
        self.document_store.write_documents(df.to_dict(orient='records'))

    @classmethod
    def set_quantized_model(cls, retriever):
        quantized_model = torch.quantization.quantize_dynamic(
            retriever.embedding_model.model,
            {torch.nn.Linear}, dtype=torch.qint8
        )
        retriever.embedding_model.model = quantized_model

    @classmethod
    def sigmoid(cls, x):
        return 1 / (1 + np.exp(-x))

    @classmethod
    def doc_to_dict(cls, doc):
        d = {}
        d['text'] = doc.text
        d['title'] = doc.meta['title']
        d['score'] = doc.query_score
        return d

    def get_topic_score_df(self, raw_results, topic_strings):
        topic_query_strings = [
            'text is about {}'.format(topic)
            for topic in topic_strings
        ]

        results = [
            self.doc_to_dict(doc)
            for doc in raw_results
        ]
        result_embeddings = np.array([
            doc.meta['text_emb']
            for doc in raw_results
        ]).astype('float32')
        topic_query_embeddings = np.array(self.retriever.embed_passages(
            list(topic_strings)
        )).astype('float32')

        scores_df = pd.DataFrame({})
        scores_df['title'] = list(map(itemgetter('title'), results))
        scores_df['text'] = list(map(itemgetter('text'), results))

        scores = pd.DataFrame(metrics.pairwise.cosine_similarity(
            result_embeddings,
            topic_query_embeddings
        ))
        scores.columns = topic_strings

        scores_df = pd.concat(
            [scores_df, self.sigmoid(scores)],
            axis=1
        )
        return scores_df