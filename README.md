## Kubeflow Dashboard Operator - a component of the Charmed Kubeflow distribution from Canonical

This repository hosts the Kubeflow Dashboard operaotr
(see [CharmHub](https://charmhub.io/kubeflow-dashboard).

Upstream documentation can be found at https://www.kubeflow.org/docs/components/central-dash/overview/

## Usage

The Kubeflow Dashboard Operator may be deployed using the Juju command line as follows
```bash
juju deploy kubeflow-dashboard --trust
```

The dashboard can't be deployed without the [Kubeflow profiles service](https://www.kubeflow.org/docs/components/multi-tenancy/getting-started/) (otherwise the charm will stuck in waiting state). Please deploy the kubeflow-pipelines operator with
```bash
juju deploy kubeflow-pipelines --trust
```

And create a relation to dashboard:
```bash
juju relate kubeflow-profiles kubeflow-dashboard
```

### Managing Dashboard Sidebar Links

Links in the dashboard can be managed through:
* relating applications to this charm on the `sidebar` relation
* adding sidebar links through the `additional-sidebar-links` config option.

Sidebar item ordering can be managed through the `sidebar-link-order` config option. 

#### Adding Sidebar Links through the `sidebar` Relation

To relate an application to this charm, use the charm library for the [KubeflowDashboardSidebarRequirer](https://github.com/canonical/kubeflow-dashboard-operator/blob/main/lib/charms/kubeflow_dashboard/v1/kubeflow_dashboard_sidebar.py).  See that file for usage instructions.

#### Adding Sidebar Links through the `additional-sidebar-links` Config

The `additional-sidebar-links` config allows for users to specify YAML or JSON input defining sidebar links.  For example, you can define a file `my_links.yaml`:

```yaml
- text: Some link
  link: /some-page
  type: item
  icon: book
- text: Some other link
  link: /some-other-page
  type: item
  icon: book
```

Where:
* text: the text shown on the sidebar
* link: the *relative* link within the platform (cannot be an external link - must be something that shares our gateway)
* type: always `item`
* icon: any icon from [here](https://kevingleason.me/Polymer-Todo/bower_components/iron-icons/demo/index.html)

To pass this to Juju, do:

```
juju config kubeflow-dashboard additional-sidebar-links=@my_links.yaml
```

To edit existing links, export them to a file, edit the file, then import back to Juju:

```
juju config kubeflow-dashboard additional-sidebar-links > links_to_edit.yaml

# edit the file

juju config kubeflow-dashboard additional-sidebar-links=@links_to_edit.yaml
```

#### Define the Order of Sidebar Links

You can define the order of the sidebar links via a YAML or JSON list of strings in the `sidebar-link-order` config.  For example:

```
juju config kubeflow-dashboard sidebar-link-order='["link1 text", "link2 text"]'
```

Where each string in the list is the `text` value that shows in the sidebar.  The charm will order the sidebar links such that:

* links that are included in `sidebar-link-order`, in the order from that configuration
* any remaining links, in alphabetical order

Any link text that is defined in `sidebar-link-order` but not matching a sidebar item will be silently ignored, this way you can set defaults without needing to update them if links are removed.

## Looking for a fully supported platform for MLOps?

Canonical [Charmed Kubeflow](https://charmed-kubeflow.io) is a state of the art, fully supported MLOps platform that helps data scientists collaborate on AI innovation on any cloud from concept to production, offered by Canonical - the publishers of [Ubuntu](https://ubuntu.com).

[![Kubeflow diagram](https://res.cloudinary.com/canonical/image/fetch/f_auto,q_auto,fl_sanitize,w_350,h_304/https://assets.ubuntu.com/v1/10400c98-Charmed-kubeflow-Topology-header.svg)](https://charmed-kubeflow.io)

Charmed Kubeflow is free to use: the solution can be deployed in any environment without constraints, paywall or restricted features. Data labs and MLOps teams only need to train their data scientists and engineers once to work consistently and efficiently on any cloud – or on-premise.

Charmed Kubeflow offers a centralised, browser-based MLOps platform that runs on any conformant Kubernetes – offering enhanced productivity, improved governance and reducing the risks associated with shadow IT.

Learn more about deploying and using Charmed Kubeflow at [https://charmed-kubeflow.io](https://charmed-kubeflow.io).

### Key features
* Centralised, browser-based data science workspaces: **familiar experience**
* Multi user: **one environment for your whole data science team**
* NVIDIA GPU support: **accelerate deep learning model training**
* Apache Spark integration: **empower big data driven model training**
* Ideation to production: **automate model training & deployment**
* AutoML: **hyperparameter tuning, architecture search**
* Composable: **edge deployment configurations available**

### What’s included in Charmed Kubeflow 1.4
* LDAP Authentication
* Jupyter Notebooks
* Work with Python and R
* Support for TensorFlow, Pytorch, MXNet, XGBoost
* TFServing, Seldon-Core
* Katib (autoML)
* Apache Spark
* Argo Workflows
* Kubeflow Pipelines

### Why engineers and data scientists choose Charmed Kubeflow
* Maintenance: Charmed Kubeflow offers up to two years of maintenance on select releases
* Optional 24/7 support available, [contact us here](https://charmed-kubeflow.io/contact-us) for more information
* Optional dedicated fully managed service available, [contact us here](https://charmed-kubeflow.io/contact-us) for more information or [learn more about Canonical’s Managed Apps service](https://ubuntu.com/managed/apps).
* Portability: Charmed Kubeflow can be deployed on any conformant Kubernetes, on any cloud or on-premise

### Documentation
Please see the [official docs site](https://charmed-kubeflow.io/docs) for complete documentation of the Charmed Kubeflow distribution.

### Bugs and feature requests
If you find a bug in our operator or want to request a specific feature, please file a bug here:
[https://github.com/canonical/dex-auth-operator/issues](https://github.com/canonical/dex-auth-operator/issues)

### License
Charmed Kubeflow is free software, distributed under the [Apache Software License, version 2.0](https://github.com/canonical/dex-auth-operator/blob/master/LICENSE).

### Contributing
Canonical welcomes contributions to Charmed Kubeflow. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the distribution.

### Security
Security issues in Charmed Kubeflow can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.