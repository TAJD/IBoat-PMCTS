#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import numpy as np
from utils import Hist
import matplotlib.pyplot as plt
from worker import UCT_COEFF
from math import log, sin, cos, pi
from matplotlib import animation
import pickle
from time import sleep
from master_node import MasterNode

sys.path.append('../model/')
from simulatorTLKT import ACTIONS, Simulator, A_DICT


class MasterTree:
    """
    Master tree that manages ns different WorkerTree in parallel.
    Each WorkerTree is searching on a different Weather scenario.
    The best policies are available after :py:meth:`get_best_policy` has been called.

    :ivar dict nodes: dictionary containing `MasterNode`, the keys are their corresponding hash
    :ivar numpy.array probability: array containing the probability of each scenario
    :ivar list Simulators: List of the simulators used during the search
    :ivar int max_depth: Maximum depth of the master tree computed after :py:meth:`get_depth` has been called
    :ivar int numScenarios: Number of scenarios
    :ivar list destination: Destination state [lat, long]
    :ivar list best_global_policy: List of actions corresponding to the average best policy
    :ivar list best_global_nodes_policy: List of MasterNodes encountered during the global best policy
    :ivar dict best_policy: Dictionary of list of actions. Key of the dictionary is the scenario id.\
     The list is the sequel of action.
    :ivar dict best_global_nodes_policy: Dictionnary of list of MasterNodes encountered during the best\
     policy of one scenario. The Key of the dictionary is the scenario id.
    """

    def __init__(self, sims, destination, nodes=dict(), proba=[]):
        num_scenarios = len(sims)
        self.nodes = nodes
        if len(nodes) == 0:
            self.nodes[hash(tuple([]))] = MasterNode(num_scenarios, nodehash=hash(tuple([])))

        self.Simulators = sims

        if len(proba) != num_scenarios:
            self.probability = np.array([1 / num_scenarios for _ in range(num_scenarios)])
        else:
            self.probability = np.array(proba)

        self.max_depth = None
        self.numScenarios = num_scenarios
        self.destination = destination
        self.best_policy = dict()
        self.best_nodes_policy = dict()

    def get_depth(self):
        """
        Compute the depth of each master node and add it in their attributes. This method is called after the search.
        """
        node = self.nodes[hash(tuple([]))]
        list_nodes = [node]
        node.depth = 0
        maxd = 0
        while list_nodes:
            node = list_nodes.pop(0)
            for n in node.children:
                list_nodes.append(n)
                n.depth = node.depth + 1
                if n.depth > maxd:
                    maxd = n.depth

        self.max_depth = maxd

    def get_best_policy(self):
        """
        Compute the best policy for each scenario and the global best policy. This method is called after the search.
        """
        # Make sure all the variable have been computed
        if not self.nodes[hash(tuple([]))].children:
            self.get_children()

        # get best global policy:
        print("Global policy")
        nodes_policy = [self.nodes[hash(tuple([]))]]  # rootNode
        policy = []
        node = nodes_policy[0]
        while node.children:
            child, action = self.get_best_child(node, idscenario=None)
            nodes_policy.append(child)
            policy.append(action)
            node = child
        self.best_policy[-1] = policy
        self.best_nodes_policy[-1] = nodes_policy

        # get best policy for each scenario:
        for id_scenario in range(len(self.Simulators)):
            print("Policy for scenario " + str(id_scenario))
            nodes_policy = [self.nodes[hash(tuple([]))]]  # rootNode
            policy = []
            node = nodes_policy[0]
            while node.children:
                child, action = self.get_best_child(node, idscenario=id_scenario)
                if child is None:
                    break
                nodes_policy.append(child)
                policy.append(action)
                node = child
            self.best_policy[id_scenario] = policy
            self.best_nodes_policy[id_scenario] = nodes_policy

    def get_best_child(self, node, idscenario=None):
        """
        Compare the children of a node based on their reward and return the best one.

        :param MasterNode node: the parent node
        :param int idscenario: id of the considered scenario. If default (None), the method return the best child\
         for the global tree
        :return: A tuple: (the best child, the action taken to go from the node to its best child)
        """
        best_reward = 0
        best_action = None
        best_child = None

        # Test if at least one node has been expanded by the scenario
        if idscenario is not None:
            if all(not child.is_expanded(idscenario) for child in node.children):
                return best_child, best_action

        for child in node.children:
            value, _ = self.get_utility(child, idscenario)
            if value > best_reward:
                best_reward = value
                best_child = child
                best_action = child.arm
        print("best reward :" + str(best_reward) + " for action :" + str(best_action))
        return best_child, best_action

    def guess_reward(self, node, idscenario):
        father = node.parentNode
        if father.is_expanded(idscenario):
            _, exploration = self.get_utility(father, idscenario)
            grandfather = father.parentNode
            best_child_grandfather, _ = self.get_best_child(grandfather, idscenario)
            value_grd, expl_grd = self.get_utility(best_child_grandfather, idscenario)
            guessed_reward = value_grd + expl_grd - exploration
        else:
            guessed_reward = father.guessed_rewards[idscenario]

        return guessed_reward

    def plot_tree(self, grey=False, idscenario=None):
        """
        Plot a 2D representation of a tree.

        :param boolean grey: if True, each node/branch are plot with a color (grey scale) depending of the depth of the node
        :param int idscenario: id of the corresponding worker tree to be plot. If None (default), the global tree is plotted.
        :return: A tuple (fig, ax) of the current plot
        """
        x0 = 0
        y0 = 0
        node = self.nodes[hash(tuple([]))]  # rootNode

        # Make sure all the variable have been computed
        if not node.children:
            self.get_children()
        if node.depth is None:
            self.get_depth()

        fig = plt.figure()
        ax = fig.add_subplot(1, 2, 1)

        if grey:
            self.plot_children(node, [x0, y0], ax, idscenario=idscenario)
        else:
            self.plot_children(node, [x0, y0], ax, 'k', idscenario=idscenario)
        ax.plot(0, 0, color="blue", marker='o', markersize='10')
        plt.axis('equal')
        fig.show()
        return fig, ax

    def get_utility(self, node, idscenario):

        num_parent = 0
        num_node = 0
        reward_per_action = np.zeros(shape=len(ACTIONS))
        for j in range(len(ACTIONS)):
            if idscenario is None:
                reward_per_action_per_scenario = []
                for i in range(self.numScenarios):
                    if node.is_expanded(i):
                        reward_per_action_per_scenario.append(node.rewards[i, j].get_mean())
                        num_node += sum(node.rewards[i, j].h)
                        num_parent += sum(node.parentNode.rewards[i, j].h)
                    else:
                        reward_guess = self.guess_reward(node, i)
                        node.guessed_rewards[i] = reward_guess
                        reward_per_action_per_scenario.append(reward_guess)

                reward_per_action[j] = np.dot(reward_per_action_per_scenario,
                                              self.probability)
            else:
                num_node += sum(node.rewards[idscenario, j].h)
                num_parent += sum(node.parentNode.rewards[idscenario, j].h)
                reward_per_action[j] = node.rewards[idscenario, j].get_mean()

        value = np.max(reward_per_action)
        exploration = UCT_COEFF * (2 * log(num_parent) / num_node) ** 0.5
        return value, exploration

    def plot_tree_colored(self, idscenario=None):
        """
        Plot a the tree 3 times: first one the colormap represents the sum of exploitation and exploration for each node
        , the second one represents the exploitation and the third one the exploration.

        :param int idscenario: id of the corresponding worker tree to be plot. If None (default), the global tree is plotted.
        :return: A tuple (fig, ax) of the current plot
        """

        def get_points(node, points, probability, coordinate=(0, 0), idscenario=None):
            """
            Recursive function used in :py:meth:`plot_tree_colored` to compute the exploration, exploitation,
            and the coordinates of a node in the plot.

            :param node: a MasterNode object
            :param list points: the previous list of points
            :param np.array probability: probability of each scenario
            :param tuple coordinate: coordinates of the previous point
            :param int idscenario: id of the corresponding worker tree to be plot. If None (default), the global tree is plotted.
            :return: the expanded list of points
            """
            x0, y0 = coordinate
            for child in node.children:
                if idscenario is not None:
                    if not child.is_expanded(idscenario):
                        continue
                x = x0 + 1 * sin(child.arm * pi / 180)
                y = y0 + 1 * cos(child.arm * pi / 180)

                if child.parentNode is not None:
                    value, exploration = self.get_utility(child,idscenario)
                    points.append((x0, y0, x, y, value + exploration, value, exploration))

                points = get_points(child, points, probability, coordinate=(x, y), idscenario=idscenario)
            return points

        node = self.nodes[hash(tuple([]))]  # rootNode

        # Make sure all the variable have been computed
        if not node.children:
            self.get_children()
        if node.depth is None:
            self.get_depth()

        # Get the coordinates and the values
        points = get_points(node, [], self.probability, idscenario=idscenario)
        x0 = [i[0] for i in points]
        y0 = [i[1] for i in points]
        x = [i[2] for i in points]
        y = [i[3] for i in points]
        total = [i[4] for i in points]
        exploitation = [i[5] for i in points]
        exploration = [i[6] for i in points]

        # Plots
        fig = plt.figure()
        ax = fig.add_subplot(1, 3, 1)
        for i in range(len(x)):
            ax.plot([x0[i], x[i]], [y0[i], y[i]], color="grey", linewidth=1, zorder=1)
        sc = ax.scatter(x, y, c=total, s=np.dot(total, 16 / max(total)), zorder=2, cmap="Reds")
        plt.colorbar(sc)
        ax.plot(0, 0, color="blue", marker='o', markersize='10')
        ax.set_title("Total utility")
        plt.axis('equal')

        ax = fig.add_subplot(1, 3, 2)
        for i in range(len(x)):
            ax.plot([x0[i], x[i]], [y0[i], y[i]], color="grey", linewidth=1, zorder=1)
        sc = ax.scatter(x, y, c=exploitation, s=np.dot(exploitation, 16 / max(exploitation)), zorder=2, cmap="Reds")
        plt.colorbar(sc)
        ax.plot(0, 0, color="blue", marker='o', markersize='10')
        ax.set_title("Exploitation")
        plt.axis('equal')

        ax = fig.add_subplot(1, 3, 3)
        for i in range(len(x)):
            ax.plot([x0[i], x[i]], [y0[i], y[i]], color="grey", linewidth=1, zorder=1)

        sc = ax.scatter(x, y, c=exploration, s=np.dot(exploration, 16 / max(exploration)), zorder=2, cmap="Reds")
        plt.colorbar(sc)
        ax.plot(0, 0, color="blue", marker='o', markersize='10')
        ax.set_title("Exploration")
        plt.axis('equal')
        fig.show()
        return fig, ax

    def plot_children(self, node, coordinate, ax, color=None, idscenario=None):
        """
        Recursive function to plot the children of a master node.

        :param MasterNode node: the parent node
        :param list coordinate: coordinate of the parent node in the representation
        :param ax: the `Axis <https://matplotlib.org/api/axes_api.html>`_ on \
        which the children are plotted
        :param color: color of the nodes/branches plotted. If None the color of the nodes/branches is a\
         grey scale depending of their depth.
        :param int idscenario: id of the scenario plotted. If None the global tree is plotted.
        """
        x0, y0 = coordinate
        for child in node.children:
            if idscenario is not None:
                if not child.is_expanded(idscenario):
                    continue
            x = x0 + 1 * sin(child.arm * pi / 180)
            y = y0 + 1 * cos(child.arm * pi / 180)
            if color is None:
                col = str((child.depth / self.max_depth) * 0.8)
            else:
                col = color
            ax.plot([x0, x], [y0, y], color=col, marker='o', markersize='6')
            self.plot_children(child, [x, y], ax, color=color, idscenario=idscenario)

    def plot_best_policy(self, grey=False, idscenario=None):
        """
        Plot a representation of a tree and its best policy.

        :param boolean grey: if True, each node/branch are plot with a color (grey scale) depending of the depth of the node
        :param int idscenario: id of the corresponding worker tree to be plot. If None (default), the global tree is plotted.
        :return: A tuple (fig, ax) of the current plot
        """
        # check if the best_policy has been computed
        if len(self.best_policy) == 0:
            self.get_best_policy()

        # Get the right policy
        if idscenario is None:
            nodes_policy = self.best_nodes_policy[-1]
        else:
            nodes_policy = self.best_nodes_policy[idscenario]

        fig, ax = self.plot_tree(grey=grey, idscenario=idscenario)
        x0 = 0
        y0 = 0
        length = 1
        for node in nodes_policy[1:]:
            x = x0 + length * sin(node.arm * pi / 180)
            y = y0 + length * cos(node.arm * pi / 180)
            ax.plot([x0, x], [y0, y], color="red", marker='o', markersize='6')
            x0 = x
            y0 = y
        return fig, ax

    def plot_hist_best_policy(self, idscenario=None):
        """
        Plot the best policy as in :py:meth:`plot_best_policy`, with the histogram of the best action at each node\
         (`Animation <https://matplotlib.org/api/animation_api.html>`_)

        :param int idscenario: id of the corresponding worker tree to be plot. If None (default), the global tree is plotted.
        :return: the `figure <https://matplotlib.org/api/figure_api.html>`_ of the current plot
        """
        # check if the best_policy has been computed
        if len(self.best_policy) == 0:
            self.get_best_policy()

        # Get the right policy
        if idscenario is None:
            nodes_policy = self.best_nodes_policy[-1]
            policy = self.best_policy[-1]
        else:
            nodes_policy = self.best_nodes_policy[idscenario]
            policy = self.best_policy[idscenario]

        # Plot
        fig, ax1 = self.plot_best_policy(grey=True, idscenario=idscenario)
        ax2 = fig.add_subplot(1, 2, 2)
        # ax2.set_ylim([0, 30])
        barcollection = ax2.bar(x=Hist.MEANS, height=[0 for _ in Hist.MEANS],
                                width=Hist.THRESH[1] - Hist.THRESH[0])
        pt, = ax1.plot(0, 0, color="green", marker='o', markersize='7')
        x0, y0 = 0, 0
        x_list = [x0]
        y_list = [y0]
        for node in nodes_policy[1:]:
            x = x0 + 1 * sin(node.arm * pi / 180)
            y = y0 + 1 * cos(node.arm * pi / 180)
            x_list.append(x)
            y_list.append(y)
            x0, y0 = x, y

        def animate(i):
            n = nodes_policy[i]
            if i == len(nodes_policy) - 1:
                # last nodes: same reward for all actions
                a = 0
            else:
                a = A_DICT[policy[i]]
            if idscenario is None:
                hist = sum(n.rewards[ii, a].h * self.probability[ii] for ii in range(len(n.rewards[:, a])))
            else:
                hist = n.rewards[idscenario, a].h
            for j, b in enumerate(barcollection):
                b.set_height(hist[j])
            ax2.set_ylim([0, np.max(hist) + 1])
            pt.set_data(x_list[i], y_list[i])

            return barcollection, pt

        anim = animation.FuncAnimation(fig, animate, frames=len(nodes_policy), interval=1000, blit=False)
        plt.show()
        return fig

    def save_tree(self, name):
        """
        Save the master tree (object) in the data Folder.

        :param name: Name of the file.
        """
        filehandler = open("../data/" + name + '.pickle', 'wb')
        pickle.dump(self, filehandler)
        filehandler.close()

    @classmethod
    def load_tree(cls, name):
        """
        Load a master tree (object) from the data Folder.

        :param name: Name of the file.
        """
        filehandler = open("../data/" + name + '.pickle', 'rb')
        loaded_tree = pickle.load(filehandler)
        filehandler.close()
        return loaded_tree
