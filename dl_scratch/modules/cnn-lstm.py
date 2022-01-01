"cnn-lstm"
"""
1. load data (pt, [n_frames, n_feature])
2. transpose to [n_features, n_frames]
3. insert pseudo axis in height [n_features, 1, n_frames]
4. abstractify channels ....-> [n_features, f_out, various]
5. average pool ....-> [n_features, f_out]

6. linear (FFC) or lstm, gru, transformer, etc.
"""
model = nn.Sequential(
    nn.Conv1d(1,8, kernel_size=30, stride=1),
    nn.Conv1d(8,16, kernel_size=20),
    nn.Conv1d(16,32, kernel_size=15),
    nn.Conv1d(32,64, kernel_size=10),
    nn.Conv1d(64,128, kernel_size=5),
    nn.Conv1d(128,128, kernel_size=3), #26, 128, 28
    nn.AdaptiveAvgPool2d((128, 1)), #26, 128, 1
    )

class AudioList(ItemList):
    @classmethod
    def from_files(cls, path, extensions = None, recurse=True, include=None, **kwargs):
        return cls(get_files(path, extensions, recurse=recurse, include=include), path, **kwargs)
    
    def get(self, fn):
        return torch.load(fn)

class Reshape():
    _order=12
    def __call__(self, item):
        w, h = item.shape
        return item.view(h, w)

class DummyChannel():
    _order = 30
    def __call__(self, item):
        return item.unsqueeze(1)

def re_labeler(fn, pat, subcl='act'):
    assert subcl in ['act', 'val', 'all']
    if subcl=='all': return ''.join(re.findall(pat, str(fn)))
    else:
        return re.findall(pat, str(fn))[0] if pat == 'act' else re.findall(pat, str(fn))[1]

al=AudioList.from_files(train_path, tfms=tfms)
label_pat = r'_(\d+)'
emotion_labeler = partial(re_labeler, pat=label_pat, subcl='all')
sd = SplitData.split_by_func(al, partial(random_splitter, p_valid=0.2))
ll = label_by_func(sd, emotion_labeler, proc_y=CategoryProcessor())
bs=64

c_in = ll.train[0][0].shape[0]
c_out = len(uniqueify(ll.train.y))
data = ll.to_databunch(bs,c_in=c_in,c_out=c_out)

masker = SpecAugment(freq_masks=2, time_masks=2, max_mask_pct=0.1)
tfms = [Reshape(), PadorTrim(250), DummyChannel(), masker]
al_dev=AudioList.from_files(dev_path, tfms=tfms)

opt_func = adam_opt(mom=0.9, mom_sqr=0.99, eps=1e-6, wd=1e-1, )
loss_func = LabelSmoothingCrossEntropy()
learn = cnn_learner(xresnet50, data, loss_func, opt_func)

st = torch.load(root_path/'checkpoints/xtesnet50-5epochs.pt')

learn.model.load_state_dict(st['model'])

def get_predictions(learn, dev):
    test_n = dev.shape[0]
    learn.model.eval()
    res = []
    with torch.no_grad():        
        for i in range((test_n-1)//bs + 1):
            xb = dev[i*bs:(i+1)*bs]
            out = learn.model(xb)
            res += [o.item() for o in out.argmax(1)]
    return res

test_items = AudioList.from_files(dev_path, tfms=tfms)

# load data
testset=torch.cat([al[idx] for idx, _ in enumerate(test_items.items)], dim=0)
testset.shape

# predict
res = get_predictions(learn, testset.unsqueeze(1))

label_convert = {0:[1, 1], 1:[0, 0], 2:[1,0], 3:[0, 1]}
submission = list(map(lambda o: label_convert[int(o)], res))

submission.__len__()

import json
def tfm_upload(fpath, result):
    out = {}
    for (k, v) in enumerate(result):
        # print(k, v); break
        k = str(k)
        out[k] = {}
        out[k]['activation'] = v[0]
        out[k]['valence'] = v[1]
        # print(out)

    with open(fpath, 'w') as f:
        json.dump(out, f)

    print(f"File written to {str(fpath)}")
    print("File looks like following format")

    print(json.dumps({'0':out['0']}, indent =2))
    # return out

trg_path = root_path/'uploads/xtesnet50-5epochs.json'
tfm_upload(trg_path, submission)

from sklearn.metrics import classification_report, f1_score, confusion_matrix

import pandas as pd

import seaborn as sn

from IPython import html, display

def get_predictions(learn):
    learn.model.eval()
    targets, outputs = [],[]
    with torch.no_grad():
        for xb,yb in progress_bar(learn.data.valid_dl):
            out = learn.model(xb)
            for _,y,z in zip(xb,yb,out):
                targets.append(learn.data.train_ds.proc_y.deproc1(y))
                outputs.append(learn.data.train_ds.proc_y.deproc1(z.argmax(-1)))
    return targets, outputs

trg, pred = get_predictions(learn)

!ls {root_path/'interpret'}

def cm(true_label, pred_label, clf, img_path=root_path/'interpret/xtesnet50-5epochs.png'):
    cm_score = confusion_matrix(true_label, pred_label)
    labels = learn.data.train_ds.proc_y.vocab
    df_cm = pd.DataFrame(cm_score, index=labels, columns=labels)
    # display(HTML(df_cm.to_html()))

    fig, ax = plt.subplots(1,1)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    fig.suptitle(f"model:{img_path.stem}, (activation, valence)")
    sn.heatmap(df_cm, annot=True, fmt='d')
    # ax.plot()
    img_path.parent.mkdir(exist_ok=True, parents=True)
    fig.tight_layout()
    fig.savefig(img_path)
    print(f"Your confusion matrix is saved at : {str(img_path.parent)} named {img_path.stem}")

cm(trg, pred, learn)

label2ls = lambda x: list(map(lambda o: o.split(''), x))