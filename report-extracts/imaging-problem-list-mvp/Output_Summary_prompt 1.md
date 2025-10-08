---

## 🧠 Results Summary

## After running the extraction (`python -m src.extract`) and evaluation (`python -m src.evaluate`) on one labeled CT Head reports for patient X:

```

== Overall ==
scope        TP    FP    FN    TN    Prec    Rec    F1
---------  ----  ----  ----  ----  ------  -----  ----
micro-avg    21    37    44    59    0.36   0.32  0.34

== By Finding ==
finding                                                 TP    FP    FN    TN    Prec    Rec    F1
----------------------------------------------------  ----  ----  ----  ----  ------  -----  ----
acute infarct                                            0     1     0     1     0     0     0
acute territorial infarction                             0     0     0     2     0     0     0
arterial flow signal                                     0     0     1     0     0     0     0
basal cisterns effacement                                0     1     0     0     0     0     0
brainstem compression                                    1     0     0     0     1     1     1
brainstem mass effect                                    0     0     3     0     0     0     0
caliber of the third and lateral ventricles decrease     0     1     0     0     0     0     0
cerebellar infarct                                       0     1     0     0     0     0     0
cerebellar tonsil displacement                           2     0     3     0     1     0.4   0.57
cerebellar tonsillar descent                             1     0     0     0     1     1     1
developing hydrocephalus                                 0     1     0     0     0     0     0
dilated lateral ventricles                               0     1     0     0     0     0     0
dilated third ventricle                                  0     1     0     0     0     0     0
dorsal brainstem mass effect                             0     1     0     0     0     0     0
edema                                                    3     0     2     0     1     0.6   0.75
effacement of basal cisterns                             0     0     1     0     0     0     0
effacement of the fourth ventricle                       0     2     0     0     0     0     0
entrapment                                               0     0     0     1     0     0     0
extra-axial collection                                   0     0     0     1     0     0     0
extra-axial collections                                  0     0     0     1     0     0     0
extra-axial fluid collection                             0     0     0     2     0     0     0
extra-axial fluid collections                            0     0     0     2     0     0     0
extracranial abnormality                                 0     0     0     1     0     0     0
fourth ventricle effacement                              0     1     0     0     0     0     0
fourth ventricular outflow tract effacement              0     1     0     0     0     0     0
hemorrhage                                               0     0     0     1     0     0     0
hemorrhagic conversion                                   1     0     1     1     1     0.5   0.67
hemorrhagic infarct                                      0     2     0     0     0     0     0
hemorrhagic transformation                               2     0     0     0     1     1     1
herniation                                               0     0     0     1     0     0     0
hydrocephalus                                            0     1     1     1     0     0     0
infarct                                                  0     1     0     1     0     0     0
inferior displacement of cerebellar tonsil               0     1     0     0     0     0     0
inferior displacement of the cerebellar tonsil           0     1     0     0     0     0     0
inferior orbital fracture                                0     1     0     0     0     0     0
infraction                                               0     0     0     1     0     0     0
intra-axial hemorrhage                                   0     0     0     1     0     0     0
intracranial hemorrhage                                  0     1     0     1     0     0     0
intraparenchymal hemorrhage                              0     0     1     0     0     0     0
lateral ventricles increase in size                      0     1     0     0     0     0     0
leftward midline shift of the posterior fossa            0     1     0     0     0     0     0
mass effect                                              3     2     0     0     0.6   1     0.75
mass effect on brainstem                                 0     1     0     0     0     0     0
mass effect on the brainstem                             0     1     0     0     0     0     0
mass lesion                                              0     0     0     1     0     0     0
mastoid air cell opacification                           0     0     0     1     0     0     0
mastoid effusion                                         1     0     0     1     1     1     1
midline shift                                            0     0     0     2     0     0     0
obstructive hydrocephalus                                0     1     2     0     0     0     0
orbital abnormality                                      0     0     0     7     0     0     0
orbital entrapment                                       0     0     0     1     0     0     0
orbital floor blowout fracture                           0     0     1     0     0     0     0
orbital fracture                                         0     0     1     0     0     0     0
osseous abnormality                                      0     0     0     1     0     0     0
paranasal sinus disease                                  0     0     0     6     0     0     0
perivascular space                                       0     0     1     0     0     0     0
periventricular hypoattenuation                          0     0     0     1     0     0     0
petechial hemorrhage                                     2     0     0     0     1     1     1
pica infarct                                             0     0     8     0     0     0     0
pica territory infarct                                   0     2     0     0     0     0     0
posterior fossa mass effect                              1     0     3     0     1     0.25  0.4
posterior fossa midline shift                            0     0     1     0     0     0     0
right cerebellar tonsil displacement                     0     1     0     0     0     0     0
right corona radiata prominent perivascular space        0     1     0     0     0     0     0
right inferior orbital floor blowout fracture            0     1     0     0     0     0     0
right pica territory infarct                             0     1     0     0     0     0     0
sinus disease                                            0     0     0     8     0     0     0
subfalcine herniation                                    0     0     0     1     0     0     0
supratentorial midline shift                             0     0     0     1     0     0     0
swelling                                                 0     1     0     0     0     0     0
t2/flair hyperintensity                                  0     0     1     0     0     0     0
temporal horn dilation                                   0     1     0     0     0     0     0
territorial infarct                                      0     0     0     1     0     0     0
tonsillar herniation                                     0     0     1     2     0     0     0
transependymal edema                                     0     0     0     1     0     0     0
transependymal flow of csf                               0     0     0     3     0     0     0
uncal herniation                                         0     0     0     1     0     0     0
ventricular compression                                  0     0     2     0     0     0     0
ventricular deviation                                    0     1     0     0     0     0     0
ventricular dilatation                                   0     1     0     0     0     0     0
ventricular effacement                                   1     0     6     0     1     0.14  0.25
ventricular enlargement                                  3     0     3     1     1     0.5   0.67
ventricular enlargment                                   0     0     1     0     0     0     0

```


