# KEYS FOR TSM-C (from TSM-A)

TSM-A cites the keys below in `sec_extA.tex` (article) and `supplement_extA.tex`
(supplement S-XV) and in the Related Work paragraph delivered to TSM-C. TSM-C is
the sole owner of the reference lists; TSM-A has NOT edited `main.tex`'s
`thebibliography` or `supplement_bib.tex`. All entries are copied from the
verified BibTeX bank in the TSM-A prompt (checked Nov 13, 2026); the
`\bibitem` lines are the same data in the article's IEEE style.

Already in `main.tex` and reused as is: `bertsimas2004`, `charnes1959`,
`rockafellar2000`, `bental2009`, `barahona2005`, `kleywegt2002`, `shapiro2009`.
The supplement (S-XV) cites `bertsimas2004`, `charnes1959`, `rockafellar2000`;
check that `supplement_bib.tex` has them (it has its own list).

## New keys, article (main.tex)

| key | used in |
|---|---|
| soyster1973 | sec:extA-paradigms; Related Work paragraph |
| bental1999robust | Related Work paragraph |
| bental2004adjustable | sec:extA-paradigms; Related Work paragraph |
| nemirovski2006chance | Related Work paragraph |
| luedtke2008sample | sec:extA-paradigms; Related Work paragraph |
| ng2007robust | Related Work paragraph |
| lowe2016robust | Related Work paragraph |
| geng2009stochastic | sec:extA-capacity |
| kouvelis2002outsourcing | sec:extA-capacity |
| wu2010intel | sec:extA-demand |
| efron1993bootstrap | sec:extA-data |
| smith2006curse | sec:extA-data |
| mak1999monte | sec:extA-data |
| bayraksan2006assessing | sec:extA-data |

## New keys, supplement (supplement_bib.tex)

soyster1973, bental2004adjustable, luedtke2008sample, geng2009stochastic,
efron1993bootstrap, smith2006curse, mak1999monte, bayraksan2006assessing,
and kleywegt2002 (already in main.tex, missing from supplement_bib.tex).
supplement_bib.tex already has bertsimas2004, charnes1959, rockafellar2000.

## BibTeX (verbatim from the bank)

```bibtex
@article{soyster1973,
  author = {A. L. Soyster}, title = {Convex Programming with Set-Inclusive Constraints and Applications to Inexact Linear Programming}, journal = {Operations Research}, volume = {21}, number = {5}, pages = {1154--1157}, year = {1973}, doi = {10.1287/opre.21.5.1154}
}
@article{bental1999robust,
  author = {A. Ben-Tal and A. Nemirovski}, title = {Robust solutions of uncertain linear programs}, journal = {Operations Research Letters}, volume = {25}, number = {1}, pages = {1--13}, year = {1999}, doi = {10.1016/S0167-6377(99)00016-4}
}
@article{bental2004adjustable,
  author = {A. Ben-Tal and A. Goryashko and E. Guslitzer and A. Nemirovski}, title = {Adjustable robust solutions of uncertain linear programs}, journal = {Mathematical Programming}, volume = {99}, number = {2}, pages = {351--376}, year = {2004}, doi = {10.1007/s10107-003-0454-y}
}
@article{nemirovski2006chance,
  author = {Arkadi Nemirovski and Alexander Shapiro}, title = {Convex Approximations of Chance Constrained Programs}, journal = {SIAM Journal on Optimization}, volume = {17}, number = {4}, pages = {969--996}, year = {2006}, doi = {10.1137/050622328}
}
@article{luedtke2008sample,
  author = {James Luedtke and Shabbir Ahmed}, title = {A Sample Approximation Approach for Optimization with Probabilistic Constraints}, journal = {SIAM Journal on Optimization}, volume = {19}, number = {2}, pages = {674--699}, year = {2008}, doi = {10.1137/070702928}
}
@inproceedings{ng2007robust,
  author = {T. S. Ng and J. Fowler}, title = {Semiconductor production planning using robust optimization}, booktitle = {Proc. IEEE Int. Conf. Industrial Engineering and Engineering Management (IEEM)}, pages = {1073--1077}, year = {2007}, doi = {10.1109/IEEM.2007.4419357}
}
@inproceedings{lowe2016robust,
  author = {Jonathan J. Lowe and Amin Khademi and Scott J. Mason}, title = {Robust semiconductor production planning under yield uncertainty}, booktitle = {Proc. Winter Simulation Conf. (WSC)}, pages = {2697--2708}, year = {2016}, doi = {10.1109/WSC.2016.7822307}
}
@article{geng2009stochastic,
  author = {Na Geng and Zhibin Jiang and Feng Chen}, title = {Stochastic programming based capacity planning for semiconductor wafer fab with uncertain demand and capacity}, journal = {European Journal of Operational Research}, volume = {198}, number = {3}, pages = {899--908}, year = {2009}, doi = {10.1016/j.ejor.2008.09.029}
}
@article{kouvelis2002outsourcing,
  author = {Panos Kouvelis and Joseph M. Milner}, title = {Supply chain capacity and outsourcing decisions: the dynamic interplay of demand and supply uncertainty}, journal = {IIE Transactions}, volume = {34}, number = {8}, pages = {717--728}, year = {2002}, doi = {10.1080/07408170208928907}
}
@article{wu2010intel,
  author = {S. David Wu and Karl G. Kempf and Mehmet O. Atan and Berrin Aytac and Shamin A. Shirodkar and Asima Mishra}, title = {Improving New-Product Forecasting at {Intel} Corporation},
  journal = {Interfaces}, volume = {40}, number = {5}, pages = {385--396}, year = {2010}, doi = {10.1287/inte.1100.0504}
}
@book{efron1993bootstrap,
  author = {Bradley Efron and Robert J. Tibshirani}, title = {An Introduction to the Bootstrap}, publisher = {Chapman \& Hall}, year = {1993}, doi = {10.1007/978-1-4899-4541-9}
}
@article{smith2006curse,
  author = {James E. Smith and Robert L. Winkler}, title = {The Optimizer's Curse: Skepticism and Postdecision Surprise in Decision Analysis}, journal = {Management Science}, volume = {52}, number = {3}, pages = {311--322}, year = {2006}, doi = {10.1287/mnsc.1050.0451}
}
@article{mak1999monte,
  author = {Wai-Kei Mak and David P. Morton and R. Kevin Wood}, title = {Monte Carlo bounding techniques for determining solution quality in stochastic programs}, journal = {Operations Research Letters}, volume = {24}, number = {1--2}, pages = {47--56}, year = {1999}, doi = {10.1016/S0167-6377(98)00054-6}
}
@article{bayraksan2006assessing,
  author = {G{\"u}zin Bayraksan and David P. Morton}, title = {Assessing solution quality in stochastic programs}, journal = {Mathematical Programming}, volume = {108}, number = {2--3}, pages = {495--514}, year = {2006}, doi = {10.1007/s10107-006-0720-x}
}
```

## Same entries as `\bibitem` (IEEE style used in main.tex)

```latex
\bibitem{soyster1973}
A.~L.~Soyster,
``Convex programming with set-inclusive constraints and applications to inexact linear programming,''
\textit{Oper.\ Res.}, vol.~21, no.~5, pp.~1154--1157, 1973.

\bibitem{bental1999robust}
A.~Ben-Tal and A.~Nemirovski,
``Robust solutions of uncertain linear programs,''
\textit{Oper.\ Res.\ Lett.}, vol.~25, no.~1, pp.~1--13, 1999.

\bibitem{bental2004adjustable}
A.~Ben-Tal, A.~Goryashko, E.~Guslitzer, and A.~Nemirovski,
``Adjustable robust solutions of uncertain linear programs,''
\textit{Math.\ Program.}, vol.~99, no.~2, pp.~351--376, 2004.

\bibitem{nemirovski2006chance}
A.~Nemirovski and A.~Shapiro,
``Convex approximations of chance constrained programs,''
\textit{SIAM J.\ Optim.}, vol.~17, no.~4, pp.~969--996, 2006.

\bibitem{luedtke2008sample}
J.~Luedtke and S.~Ahmed,
``A sample approximation approach for optimization with probabilistic constraints,''
\textit{SIAM J.\ Optim.}, vol.~19, no.~2, pp.~674--699, 2008.

\bibitem{ng2007robust}
T.~S.~Ng and J.~Fowler,
``Semiconductor production planning using robust optimization,''
in \textit{Proc.\ IEEE Int.\ Conf.\ Ind.\ Eng.\ Eng.\ Manag.\ (IEEM)}, 2007, pp.~1073--1077.

\bibitem{lowe2016robust}
J.~J.~Lowe, A.~Khademi, and S.~J.~Mason,
``Robust semiconductor production planning under yield uncertainty,''
in \textit{Proc.\ Winter Simul.\ Conf.\ (WSC)}, 2016, pp.~2697--2708.

\bibitem{geng2009stochastic}
N.~Geng, Z.~Jiang, and F.~Chen,
``Stochastic programming based capacity planning for semiconductor wafer fab with uncertain demand and capacity,''
\textit{Eur.\ J.\ Oper.\ Res.}, vol.~198, no.~3, pp.~899--908, 2009.

\bibitem{kouvelis2002outsourcing}
P.~Kouvelis and J.~M.~Milner,
``Supply chain capacity and outsourcing decisions: The dynamic interplay of demand and supply uncertainty,''
\textit{IIE Trans.}, vol.~34, no.~8, pp.~717--728, 2002.

\bibitem{wu2010intel}
S.~D.~Wu, K.~G.~Kempf, M.~O.~Atan, B.~Aytac, S.~A.~Shirodkar, and A.~Mishra,
``Improving new-product forecasting at Intel Corporation,''
\textit{Interfaces}, vol.~40, no.~5, pp.~385--396, 2010.

\bibitem{efron1993bootstrap}
B.~Efron and R.~J.~Tibshirani,
\textit{An Introduction to the Bootstrap}.
Chapman \& Hall, 1993.

\bibitem{smith2006curse}
J.~E.~Smith and R.~L.~Winkler,
``The optimizer's curse: Skepticism and postdecision surprise in decision analysis,''
\textit{Manag.\ Sci.}, vol.~52, no.~3, pp.~311--322, 2006.

\bibitem{mak1999monte}
W.-K.~Mak, D.~P.~Morton, and R.~K.~Wood,
``Monte Carlo bounding techniques for determining solution quality in stochastic programs,''
\textit{Oper.\ Res.\ Lett.}, vol.~24, no.~1--2, pp.~47--56, 1999.

\bibitem{bayraksan2006assessing}
G.~Bayraksan and D.~P.~Morton,
``Assessing solution quality in stochastic programs,''
\textit{Math.\ Program.}, vol.~108, no.~2--3, pp.~495--514, 2006.
```

Note: the bank entry for efron1993bootstrap gives no publisher city, so none is given here.
