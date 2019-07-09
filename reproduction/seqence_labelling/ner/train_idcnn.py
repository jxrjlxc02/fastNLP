from reproduction.seqence_labelling.ner.data.OntoNoteLoader import OntoNoteNERDataLoader
from fastNLP.core.callback import FitlogCallback, LRScheduler
from fastNLP import GradientClipCallback
from torch.optim.lr_scheduler import LambdaLR, CosineAnnealingLR
from torch.optim import SGD, Adam
from fastNLP import Const
from fastNLP import RandomSampler, BucketSampler
from fastNLP import SpanFPreRecMetric
from fastNLP import Trainer
from reproduction.seqence_labelling.ner.model.dilated_cnn import IDCNN
from fastNLP.core.utils import Option
from fastNLP.modules.encoder.embedding import CNNCharEmbedding, StaticEmbedding
from fastNLP.core.utils import cache_results
import sys
import torch.cuda
import os
os.environ['FASTNLP_BASE_URL'] = 'http://10.141.222.118:8888/file/download/'
os.environ['FASTNLP_CACHE_DIR'] = '/remote-home/hyan01/fastnlp_caches'
os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"

encoding_type = 'bioes'


def get_path(path):
    return os.path.join(os.environ['HOME'], path)

data_path = get_path('workdir/datasets/ontonotes-v4')

ops = Option(
    batch_size=128,
    num_epochs=100,
    lr=3e-4,
    repeats=3,
    num_layers=3,
    num_filters=400,
    use_crf=True,
    gradient_clip=5,
)

@cache_results('ontonotes-cache')
def load_data():

    data = OntoNoteNERDataLoader(encoding_type=encoding_type).process(data_path,
                                                                  lower=True)

    # char_embed = CNNCharEmbedding(vocab=data.vocabs['cap_words'], embed_size=30, char_emb_size=30, filter_nums=[30],
    #                               kernel_sizes=[3])

    word_embed = StaticEmbedding(vocab=data.vocabs[Const.INPUT],
                                 model_dir_or_name='en-glove-840b-300',
                                 requires_grad=True)
    return data, [word_embed]

data, embeds = load_data()
print(data.datasets['train'][0])
print(list(data.vocabs.keys()))

for ds in data.datasets.values():
    ds.rename_field('cap_words', 'chars')
    ds.set_input('chars')

word_embed = embeds[0]
char_embed = CNNCharEmbedding(data.vocabs['cap_words'])
# for ds in data.datasets:
#     ds.rename_field('')

print(data.vocabs[Const.TARGET].word2idx)

model = IDCNN(init_embed=word_embed,
              char_embed=char_embed,
              num_cls=len(data.vocabs[Const.TARGET]),
              repeats=ops.repeats,
              num_layers=ops.num_layers,
              num_filters=ops.num_filters,
              kernel_size=3,
              use_crf=ops.use_crf, use_projection=True,
              block_loss=True,
              input_dropout=0.33, hidden_dropout=0.2, inner_dropout=0.2)

print(model)

callbacks = [GradientClipCallback(clip_value=ops.gradient_clip, clip_type='norm'),]

optimizer = Adam(model.parameters(), lr=ops.lr, weight_decay=0)
# scheduler = LRScheduler(LambdaLR(optimizer, lr_lambda=lambda epoch: 1 / (1 + 0.05 * epoch)))
# callbacks.append(LRScheduler(CosineAnnealingLR(optimizer, 15)))
# optimizer = SWATS(model.parameters(), verbose=True)
# optimizer = Adam(model.parameters(), lr=0.005)

device = 'cuda:0' if torch.cuda.is_available() else 'cpu'

trainer = Trainer(train_data=data.datasets['train'], model=model, optimizer=optimizer,
                  sampler=BucketSampler(num_buckets=50, batch_size=ops.batch_size),
                  device=device, dev_data=data.datasets['dev'], batch_size=ops.batch_size,
                  metrics=SpanFPreRecMetric(
                      tag_vocab=data.vocabs[Const.TARGET], encoding_type=encoding_type),
                  check_code_level=-1,
                  callbacks=callbacks, num_workers=2, n_epochs=ops.num_epochs)
trainer.train()